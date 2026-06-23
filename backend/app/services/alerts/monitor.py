"""Periodic alert evaluation for KR/US symbols."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.schemas.portfolio import OrderRequest, OrderType
from backend.app.services.brokers.base import BrokerAccountRef
from backend.app.services.kis.rest_client import KISRestClient
from backend.app.services.toss.rest_client import TossRestClient
from shared.db.models import Alert, Setting
from shared.db.session import service_session
from shared.domain.account import AccountType, BrokerType
from shared.domain.trade import TradeDirection

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AlertEvaluationSummary:
    started_at: datetime
    finished_at: datetime | None = None
    seen: int = 0
    checked: int = 0
    triggered: int = 0
    ordered: int = 0
    errors: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "seen": self.seen,
            "checked": self.checked,
            "triggered": self.triggered,
            "ordered": self.ordered,
            "errors": self.errors,
            "details": self.details,
        }


class AlertMonitorService:
    """Evaluate enabled, untriggered alerts at a fixed interval."""

    def __init__(self, *, interval_seconds: int | None = None) -> None:
        self._interval_seconds = interval_seconds or settings.ALERT_MONITOR_INTERVAL_SECONDS
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="alert-monitor")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while self._running:
            try:
                summary = await evaluate_alerts_once()
                logger.info(
                    "alert monitor checked=%s triggered=%s errors=%s",
                    summary.checked,
                    summary.triggered,
                    summary.errors,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("alert monitor loop failed")
            await asyncio.sleep(max(5, self._interval_seconds))


async def evaluate_alerts_once() -> AlertEvaluationSummary:
    """Evaluate all pending alerts once.

    This is safe to expose as a manual API/test hook; it does not place live
    orders unless an alert explicitly asks for BUY/SELL and
    ``ALERT_ORDER_IS_MOCK=false``.
    """

    now = datetime.now().astimezone()
    summary = AlertEvaluationSummary(started_at=now)

    async with service_session() as session:
        rows_result = await session.execute(select(Setting))
        settings_rows = {row.key: row.value for row in rows_result.scalars()}

        result = await session.execute(
            select(Alert)
            .where(Alert.triggered_at.is_(None))
            .where(Alert.is_enabled.is_(True))
            .order_by(Alert.created_at.asc(), Alert.id.asc())
        )
        alerts = list(result.scalars())
        summary.seen = len(alerts)

        kis_client = KISRestClient()
        toss_client = TossRestClient.from_settings_map(settings_rows)

        for alert in alerts:
            detail: dict[str, Any] = {
                "alert_id": alert.id,
                "symbol": _alert_symbol(alert),
                "broker": _alert_broker(alert).value,
            }
            try:
                quote = await _fetch_alert_quote(alert, kis_client, toss_client)
                summary.checked += 1
                alert.last_checked_at = now
                alert.last_price = float(quote["price"])
                alert.last_error = None
                detail.update(
                    {
                        "price": float(quote["price"]),
                        "change_pct": (
                            float(quote["change_pct"])
                            if quote["change_pct"] is not None
                            else None
                        ),
                    }
                )

                if not _is_triggered(alert, quote):
                    detail["status"] = "not_triggered"
                    summary.details.append(detail)
                    continue

                alert.triggered_at = now
                summary.triggered += 1
                detail["status"] = "triggered"

                order_payload = await _maybe_place_alert_order(
                    alert,
                    kis_client,
                    toss_client,
                )
                if order_payload is not None:
                    summary.ordered += 1
                    detail["order"] = order_payload

                summary.details.append(detail)
            except Exception as exc:
                summary.errors += 1
                alert.last_checked_at = now
                alert.last_error = str(exc)[:500]
                detail["status"] = "error"
                detail["error"] = alert.last_error
                summary.details.append(detail)
                logger.exception("failed to evaluate alert id=%s", alert.id)

        await session.commit()

    summary.finished_at = datetime.now().astimezone()
    return summary


async def _fetch_alert_quote(
    alert: Alert,
    kis_client: KISRestClient,
    toss_client: TossRestClient,
) -> dict[str, Decimal | None]:
    broker = _alert_broker(alert)
    symbol = _alert_symbol(alert)
    if broker is BrokerType.TOSS or _market_country(alert) == "US":
        quote = await toss_client.get_current_price(
            symbol,
            account=BrokerAccountRef(
                broker=BrokerType.TOSS,
                account_id=alert.account_id,
            ),
        )
        return {
            "price": quote.last_price,
            "change_pct": _decimal_from_raw(quote.raw or {}, "changePct", "changeRate"),
        }

    if not symbol.isdigit():
        raise ValueError("KIS alerts require a 6-digit Korean stock code.")
    account_type = _alert_account_type(alert)
    quote = await kis_client.get_current_price(account_type, symbol.zfill(6))
    return {"price": quote.current_price, "change_pct": quote.change_pct}


async def _maybe_place_alert_order(
    alert: Alert,
    kis_client: KISRestClient,
    toss_client: TossRestClient,
) -> dict[str, Any] | None:
    action = str(alert.action or "NOTIFY").upper()
    if action not in {"BUY", "SELL"}:
        return None
    quantity = int(alert.order_quantity or 0)
    if quantity <= 0:
        return {"mock": True, "skipped": "order_quantity is required for BUY/SELL alerts"}

    direction = TradeDirection.BUY if action == "BUY" else TradeDirection.SELL
    broker = _alert_broker(alert)
    request = OrderRequest(
        broker=broker,
        account_type=_alert_account_type(alert),
        account_id=alert.account_id,
        stock_code=_alert_symbol(alert),
        direction=direction,
        quantity=quantity,
        order_type=OrderType.MARKET,
        price=None,
        exchange_id="KRX" if _market_country(alert) == "KR" else "NASD",
    )

    if settings.ALERT_ORDER_IS_MOCK:
        logger.warning(
            "alert mock order alert_id=%s broker=%s side=%s symbol=%s qty=%s",
            alert.id,
            broker.value,
            direction.value,
            request.stock_code,
            quantity,
        )
        return {
            "mock": True,
            "broker": broker.value,
            "direction": direction.value,
            "symbol": request.stock_code,
            "quantity": quantity,
        }

    if broker is BrokerType.TOSS:
        response = await toss_client.place_order(request)
    else:
        if not request.stock_code.isdigit():
            raise ValueError("KIS orders require a 6-digit Korean stock code.")
        response = await kis_client.place_order(request)

    return response.model_dump(mode="json")


def _is_triggered(alert: Alert, quote: dict[str, Decimal | None]) -> bool:
    condition = str(alert.condition or "").upper()
    price = quote["price"]
    change_pct = quote.get("change_pct")
    threshold = Decimal(str(alert.threshold))

    if condition in {"PRICE_ABOVE", "PRICE_GTE"}:
        return price is not None and price >= threshold
    if condition in {"PRICE_BELOW", "PRICE_LTE"}:
        return price is not None and price <= threshold
    if condition == "PCT_RISE":
        return change_pct is not None and change_pct >= abs(threshold)
    if condition == "PCT_DROP":
        return change_pct is not None and change_pct <= -abs(threshold)
    if condition == "PCT_CHANGE":
        if change_pct is None:
            return False
        if threshold < 0:
            return change_pct <= threshold
        return change_pct >= threshold
    if condition == "VOLUME_SPIKE":
        raise ValueError("VOLUME_SPIKE alerts need historical volume baseline support.")
    raise ValueError(f"Unsupported alert condition: {alert.condition}")


def _alert_broker(alert: Alert) -> BrokerType:
    try:
        return BrokerType(str(alert.broker or settings.ALERT_DEFAULT_BROKER).upper())
    except ValueError:
        return settings.ALERT_DEFAULT_BROKER


def _alert_account_type(alert: Alert) -> AccountType:
    try:
        return AccountType(str(alert.account_type or settings.KIS_DEFAULT_ACCOUNT).upper())
    except ValueError:
        return settings.KIS_DEFAULT_ACCOUNT


def _market_country(alert: Alert) -> str:
    value = str(alert.market_country or "").upper().strip()
    if value in {"KR", "US"}:
        return value
    symbol = _alert_symbol(alert)
    return "KR" if symbol.isdigit() else "US"


def _alert_symbol(alert: Alert) -> str:
    raw = str(alert.symbol or alert.stock_code or "").strip().upper()
    return raw.zfill(6) if raw.isdigit() else raw


def _decimal_from_raw(raw: dict[str, object], *keys: str) -> Decimal | None:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return Decimal(str(value).replace(",", ""))
    return None


def alert_monitor_settings_payload() -> dict[str, Any]:
    return {
        "autostart": settings.ALERT_MONITOR_AUTOSTART,
        "interval_seconds": settings.ALERT_MONITOR_INTERVAL_SECONDS,
        "order_is_mock": settings.ALERT_ORDER_IS_MOCK,
        "default_broker": settings.ALERT_DEFAULT_BROKER.value,
    }


def serialize_alert_metadata(alert: Alert) -> str:
    return json.dumps(
        {
            "broker": str(alert.broker or "KIS"),
            "market_country": str(alert.market_country or "KR"),
            "symbol": _alert_symbol(alert),
            "action": str(alert.action or "NOTIFY"),
            "order_quantity": alert.order_quantity,
            "last_checked_at": (
                alert.last_checked_at.isoformat() if alert.last_checked_at else None
            ),
            "last_price": alert.last_price,
            "last_error": alert.last_error,
        },
        ensure_ascii=False,
    )
