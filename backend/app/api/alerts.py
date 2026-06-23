"""Alert history and CRUD API."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.alerts.monitor import (
    alert_monitor_settings_payload,
    evaluate_alerts_once,
)
from backend.app.services.market_data.names import lookup_stock_names
from shared.db.models import Alert
from shared.db.session import get_service_session
from shared.domain.account import AccountType, BrokerType

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

AlertConditionWire = Literal[
    "PRICE_ABOVE",
    "PRICE_BELOW",
    "PCT_CHANGE",
    "VOLUME_SPIKE",
]

AlertActionWire = Literal["NOTIFY", "BUY", "SELL"]
MarketCountryWire = Literal["KR", "US"]


class AlertCreate(BaseModel):
    stock_code: str = Field(min_length=1, max_length=20)
    broker: BrokerType = BrokerType.KIS
    market_country: MarketCountryWire | None = None
    symbol: str | None = Field(default=None, min_length=1, max_length=20)
    condition: AlertConditionWire
    threshold: float
    action: AlertActionWire = "NOTIFY"
    order_quantity: int | None = Field(default=None, gt=0)
    account_type: AccountType = AccountType.PAPER
    account_id: str | None = None
    is_enabled: bool = True

    @field_validator("stock_code")
    @classmethod
    def normalize_stock_code(cls, value: str) -> str:
        return _normalize_symbol(value)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        return _normalize_symbol(value) if value else None


class AlertPostMortemPatch(BaseModel):
    post_mortem: str = Field(min_length=1)

    @field_validator("post_mortem")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("post_mortem must not be blank")
        return stripped


class AlertResponse(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    broker: BrokerType = BrokerType.KIS
    market_country: str
    symbol: str
    condition: str
    threshold: float
    action: str
    order_quantity: int | None
    account_type: str | None
    account_id: str | None
    is_enabled: bool
    last_checked_at: datetime | None
    last_price: float | None
    last_error: str | None
    status: Literal["pending", "triggered", "cancelled"]
    created_at: datetime
    triggered_at: datetime | None
    post_mortem: str | None


@router.get("", response_model=ApiEnvelope[list[AlertResponse]])
async def list_alerts(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[list[AlertResponse]]:
    stmt = select(Alert)
    if from_ is not None:
        stmt = stmt.where(Alert.created_at >= from_)
    if to is not None:
        stmt = stmt.where(Alert.created_at <= to)
    stmt = stmt.order_by(Alert.created_at.desc(), Alert.id.desc())
    result = await session.execute(stmt)
    alerts = list(result.scalars())
    return ApiEnvelope(data=await _alert_responses(alerts), error=None)


@router.post(
    "",
    response_model=ApiEnvelope[AlertResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_alert(
    payload: AlertCreate,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[AlertResponse]:
    symbol = payload.symbol or payload.stock_code
    market_country = payload.market_country or ("KR" if symbol.isdigit() else "US")
    broker = payload.broker
    if market_country == "US" and broker is BrokerType.KIS:
        broker = BrokerType.TOSS
    alert = Alert(
        stock_code=payload.stock_code,
        broker=broker.value,
        market_country=market_country,
        symbol=symbol,
        condition=payload.condition,
        threshold=payload.threshold,
        action=payload.action,
        order_quantity=payload.order_quantity,
        account_type=payload.account_type.value,
        account_id=payload.account_id,
        is_enabled=payload.is_enabled,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return ApiEnvelope(data=(await _alert_responses([alert]))[0], error=None)


@router.post("/evaluate", response_model=ApiEnvelope[dict[str, Any]])
async def evaluate_alerts() -> ApiEnvelope[dict[str, Any]]:
    """Evaluate pending alerts once without waiting for the background loop."""

    summary = await evaluate_alerts_once()
    return ApiEnvelope(data=summary.to_dict(), error=None)


@router.get("/monitor", response_model=ApiEnvelope[dict[str, Any]])
async def get_alert_monitor_settings() -> ApiEnvelope[dict[str, Any]]:
    return ApiEnvelope(data=alert_monitor_settings_payload(), error=None)


@router.delete("/{alert_id}", response_model=ApiEnvelope[dict[str, Any]])
async def delete_alert(
    alert_id: int,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[dict[str, Any]]:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    await session.delete(alert)
    await session.commit()
    return ApiEnvelope(data={"deleted": True, "id": alert_id}, error=None)


@router.patch(
    "/{alert_id}/post-mortem",
    response_model=ApiEnvelope[AlertResponse],
)
async def patch_alert_post_mortem(
    alert_id: int,
    payload: AlertPostMortemPatch,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[AlertResponse]:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.post_mortem = payload.post_mortem
    await session.commit()
    await session.refresh(alert)
    return ApiEnvelope(data=(await _alert_responses([alert]))[0], error=None)


async def _alert_responses(alerts: list[Alert]) -> list[AlertResponse]:
    domestic_codes = [
        _alert_symbol(alert)
        for alert in alerts
        if _alert_market_country(alert) == "KR" and _alert_symbol(alert).isdigit()
    ]
    names = await asyncio.to_thread(
        lookup_stock_names,
        domestic_codes,
    )
    return [
        AlertResponse(
            id=alert.id,
            stock_code=alert.stock_code,
            stock_name=names.get(_alert_symbol(alert)) or _alert_symbol(alert),
            broker=_alert_broker(alert),
            market_country=_alert_market_country(alert),
            symbol=_alert_symbol(alert),
            condition=_to_flutter_condition(alert.condition),
            threshold=alert.threshold,
            action=str(alert.action or "NOTIFY").upper(),
            order_quantity=alert.order_quantity,
            account_type=alert.account_type,
            account_id=alert.account_id,
            is_enabled=bool(alert.is_enabled),
            last_checked_at=alert.last_checked_at,
            last_price=alert.last_price,
            last_error=alert.last_error,
            status="triggered" if alert.triggered_at is not None else "pending",
            created_at=alert.created_at,
            triggered_at=alert.triggered_at,
            post_mortem=alert.post_mortem,
        )
        for alert in alerts
    ]


def _to_flutter_condition(condition: str) -> str:
    mapping = {
        "PRICE_GTE": "PRICE_ABOVE",
        "PRICE_LTE": "PRICE_BELOW",
        "PCT_DROP": "PCT_CHANGE",
        "PCT_RISE": "PCT_CHANGE",
    }
    return mapping.get(condition.upper(), condition.upper())


def _normalize_symbol(value: str) -> str:
    stripped = value.strip().upper()
    return stripped.zfill(6) if stripped.isdigit() else stripped


def _alert_symbol(alert: Alert) -> str:
    value = str(alert.symbol or alert.stock_code or "").strip().upper()
    return value.zfill(6) if value.isdigit() else value


def _alert_market_country(alert: Alert) -> str:
    value = str(alert.market_country or "").upper().strip()
    if value in {"KR", "US"}:
        return value
    return "KR" if _alert_symbol(alert).isdigit() else "US"


def _alert_broker(alert: Alert) -> BrokerType:
    try:
        return BrokerType(str(alert.broker or "KIS").upper())
    except ValueError:
        return BrokerType.KIS
