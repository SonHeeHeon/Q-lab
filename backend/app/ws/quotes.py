"""FastAPI WebSocket fan-out hub for real-time quote ticks."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.services.kis.ws_client import QuoteTick

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
            await _upstream_client.subscribe(codes)
        return {
            "type": "subscribed",
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
