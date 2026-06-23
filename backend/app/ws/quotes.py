"""FastAPI WebSocket fan-out hub for real-time quote ticks."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.core.config import settings
from backend.app.services.kis.ws_client import QuoteTick
from backend.app.services.market_data.quotes import fetch_current_quotes
from shared.domain.account import AccountType, BrokerType

if TYPE_CHECKING:
    from backend.app.services.kis.ws_client import KISWebSocketClient

logger = logging.getLogger(__name__)
router = APIRouter()

_upstream_client: KISWebSocketClient | None = None


class QuoteConnectionManager:
    """Tracks downstream clients and their requested stock codes."""

    def __init__(self) -> None:
        self._subscriptions: dict[WebSocket, set[str]] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._subscriptions[websocket] = set()

    def disconnect(self, websocket: WebSocket) -> None:
        self._subscriptions.pop(websocket, None)

    def subscribe(self, websocket: WebSocket, codes: set[str]) -> None:
        self._subscriptions.setdefault(websocket, set()).update(codes)

    def unsubscribe(self, websocket: WebSocket, codes: set[str]) -> None:
        self._subscriptions.setdefault(websocket, set()).difference_update(codes)

    def all_requested_codes(self) -> set[str]:
        requested: set[str] = set()
        for codes in self._subscriptions.values():
            requested.update(codes)
        return requested

    async def broadcast_tick(self, tick: QuoteTick) -> None:
        payload = tick.to_payload()
        stale_connections: list[WebSocket] = []

        for websocket, codes in list(self._subscriptions.items()):
            if codes and tick.code not in codes:
                continue
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale_connections.append(websocket)

        for websocket in stale_connections:
            self.disconnect(websocket)


quote_manager = QuoteConnectionManager()


def set_upstream_client(client: KISWebSocketClient | None) -> None:
    global _upstream_client
    _upstream_client = client


@router.websocket("/ws/quotes")
async def quotes_websocket(websocket: WebSocket) -> None:
    await quote_manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            response = await _handle_client_message(websocket, message)
            if response is not None:
                await websocket.send_json(response)
    except WebSocketDisconnect:
        quote_manager.disconnect(websocket)
    except Exception:
        logger.exception("downstream quote websocket failed")
        quote_manager.disconnect(websocket)
        await websocket.close(code=1011)


async def _handle_client_message(
    websocket: WebSocket,
    message: str,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return {"type": "error", "code": "BAD_JSON", "message": "Invalid JSON."}

    action = payload.get("action")
    codes = _normalize_codes(payload.get("codes", []))

    if action == "subscribe":
        quote_manager.subscribe(websocket, codes)
        if _upstream_client is not None:
            await _upstream_client.subscribe(_domestic_codes(codes))
        await _send_initial_quote_snapshots(
            websocket,
            codes,
            broker=BrokerType.KIS,
            account_type=_upstream_client.account_type if _upstream_client else settings.KIS_DEFAULT_ACCOUNT,
        )
        return {
            "type": "subscribed",
            "codes": sorted(codes),
        }

    if action == "snapshot":
        broker = _parse_broker(payload.get("broker"))
        account_type = _parse_account_type(payload.get("account_type"))
        account_id = (
            str(payload.get("account_id")).strip()
            if payload.get("account_id") is not None
            else None
        )
        await _send_initial_quote_snapshots(
            websocket,
            codes,
            broker=broker,
            account_type=account_type,
            account_id=account_id,
        )
        return {
            "type": "snapshot",
            "broker": broker.value,
            "codes": sorted(codes),
        }

    if action == "unsubscribe":
        quote_manager.unsubscribe(websocket, codes)
        return {
            "type": "unsubscribed",
            "codes": sorted(codes),
        }

    return {
        "type": "error",
        "code": "UNKNOWN_ACTION",
        "message": "Use action=subscribe or action=unsubscribe.",
    }


def _normalize_codes(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(code).strip() for code in value if str(code).strip()}


async def _send_initial_quote_snapshots(
    websocket: WebSocket,
    codes: set[str],
    *,
    broker: BrokerType,
    account_type: AccountType,
    account_id: str | None = None,
) -> None:
    """Send one REST quote immediately so UI sheets do not fall back to avg cost.

    KIS websocket ticks are sparse outside active trading and may arrive after a
    modal has already rendered. A cheap one-shot REST quote keeps portfolio rows
    and order sheets aligned with the latest known market price without changing
    the Flutter contract.
    """

    symbols = _domestic_codes(codes) if broker is BrokerType.KIS else {
        str(code).strip().upper() for code in codes if str(code).strip()
    }
    if not symbols:
        return

    result = await fetch_current_quotes(
        broker=broker,
        symbols=sorted(symbols),
        account_type=account_type,
        account_id=account_id,
    )
    timestamp = datetime.now(ZoneInfo(settings.APSCHEDULER_TIMEZONE))
    for quote in result.quotes:
        await websocket.send_json(
            {
                "type": "tick",
                "code": quote.symbol,
                "price": float(quote.price),
                "volume": quote.volume or 0,
                "change_pct": float(quote.change_pct or 0),
                "timestamp": (
                    quote.timestamp.isoformat()
                    if isinstance(quote.timestamp, datetime)
                    else (quote.timestamp or timestamp.isoformat())
                ),
            }
        )
    for symbol, error in result.errors.items():
        logger.debug("failed to send quote snapshot for %s/%s: %s", broker.value, symbol, error)


def _domestic_codes(codes: set[str]) -> set[str]:
    return {code.zfill(6) for code in codes if code.isdigit()}


def _parse_broker(value: Any) -> BrokerType:
    try:
        return BrokerType(str(value or BrokerType.KIS.value).upper())
    except ValueError:
        return BrokerType.KIS


def _parse_account_type(value: Any) -> AccountType:
    try:
        return AccountType(str(value or settings.KIS_DEFAULT_ACCOUNT.value).upper())
    except ValueError:
        return settings.KIS_DEFAULT_ACCOUNT
