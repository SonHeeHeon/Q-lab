"""KIS WebSocket client for real-time quote ticks."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import websockets
from websockets.exceptions import ConnectionClosed

from backend.app.core.config import Settings, settings
from backend.app.services.kis.accounts import KISAccountRegistry
from backend.app.services.kis.auth import KISAuthError, KISTokenManager
from shared.domain.account import AccountType

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
REALTIME_TRADE_TR_ID = "H0STCNT0"


@dataclass(frozen=True, slots=True)
class QuoteTick:
    code: str
    price: int
    volume: int
    change_pct: float
    timestamp: datetime
    tr_id: str = REALTIME_TRADE_TR_ID

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "tick",
            "code": self.code,
            "price": self.price,
            "volume": self.volume,
            "change_pct": self.change_pct,
            "timestamp": self.timestamp.isoformat(),
        }


TickCallback = Callable[[QuoteTick], Awaitable[None] | None]


class KISWebSocketClient:
    """Long-lived KIS WebSocket connection with reconnect and subscriptions."""

    def __init__(
        self,
        account_type: AccountType,
        *,
        on_tick: TickCallback | None = None,
        app_settings: Settings = settings,
        registry: KISAccountRegistry | None = None,
        token_manager: KISTokenManager | None = None,
    ) -> None:
        self.account_type = account_type
        self._settings = app_settings
        self._registry = registry or KISAccountRegistry(app_settings)
        self._token_manager = token_manager or KISTokenManager(app_settings)
        self._on_tick = on_tick
        self._subscribed_codes: set[str] = set()
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._websocket: Any | None = None
        self._approval_key: str | None = None
        self._send_lock = asyncio.Lock()

    @property
    def subscribed_codes(self) -> set[str]:
        return set(self._subscribed_codes)

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(
            self.run_forever(),
            name=f"kis-ws-{self.account_type.value.lower()}",
        )

    async def stop(self) -> None:
        self._running = False
        if self._websocket is not None:
            await self._websocket.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def subscribe(self, codes: list[str] | set[str]) -> None:
        normalized = self._normalize_codes(codes)
        new_codes = normalized - self._subscribed_codes
        self._subscribed_codes.update(normalized)
        if self._websocket is not None and new_codes:
            await self._send_subscriptions(new_codes, tr_type="1")

    async def unsubscribe(self, codes: list[str] | set[str]) -> None:
        normalized = self._normalize_codes(codes)
        existing_codes = normalized & self._subscribed_codes
        self._subscribed_codes.difference_update(normalized)
        if self._websocket is not None and existing_codes:
            await self._send_subscriptions(existing_codes, tr_type="2")

    async def run_forever(self) -> None:
        backoff_seconds = 1
        max_backoff = self._settings.KIS_WS_RECONNECT_MAX_SECONDS
        endpoint = self._registry.get_endpoints(self.account_type).websocket_url

        while self._running:
            try:
                self._approval_key = await self._token_manager.get_approval_key(
                    self.account_type
                )
                async with websockets.connect(
                    endpoint,
                    ping_interval=None,
                    open_timeout=self._settings.KIS_HTTP_TIMEOUT_SECONDS,
                ) as websocket:
                    self._websocket = websocket
                    backoff_seconds = 1
                    logger.info("connected to KIS websocket: %s", endpoint)
                    await self._send_subscriptions(self._subscribed_codes, tr_type="1")

                    async for message in websocket:
                        await self._handle_message(message)

            except asyncio.CancelledError:
                raise
            except KISAuthError:
                logger.exception("KIS auth failed before websocket connection")
            except ConnectionClosed:
                logger.warning("KIS websocket connection closed")
            except Exception:
                logger.exception("KIS websocket loop failed")
            finally:
                self._websocket = None

            if self._running:
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, max_backoff)

    async def _handle_message(self, message: str | bytes) -> None:
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")

        if "PINGPONG" in message:
            if self._websocket is not None:
                await self._websocket.send(message)
            return

        tick = self.parse_tick_frame(message)
        if tick is None:
            self._log_control_frame(message)
            return

        if self._on_tick is None:
            return

        result = self._on_tick(tick)
        if inspect.isawaitable(result):
            await result

    async def _send_subscriptions(self, codes: set[str], *, tr_type: str) -> None:
        if self._websocket is None or not codes:
            return
        if self._approval_key is None:
            self._approval_key = await self._token_manager.get_approval_key(
                self.account_type
            )

        async with self._send_lock:
            for code in sorted(set(codes)):
                payload = self._subscription_payload(code, tr_type=tr_type)
                await self._websocket.send(json.dumps(payload, ensure_ascii=False))
                await asyncio.sleep(0.05)

    def _subscription_payload(self, code: str, *, tr_type: str) -> dict[str, Any]:
        return {
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": tr_type,
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": REALTIME_TRADE_TR_ID,
                    "tr_key": code,
                }
            },
        }

    def parse_tick_frame(self, message: str) -> QuoteTick | None:
        if not message.startswith("0|"):
            return None

        parts = message.split("|", 3)
        if len(parts) != 4:
            return None

        _, tr_id, _count, raw_fields = parts
        if tr_id != REALTIME_TRADE_TR_ID:
            return None

        fields = raw_fields.split("^")
        if len(fields) < 14:
            return None

        code = fields[0].strip()
        price = self._to_int(fields[2])
        change_pct = self._to_float(fields[5])
        volume = self._to_int(fields[13] or fields[12])
        timestamp = self._parse_tick_time(fields[1])

        if not code or price <= 0:
            return None

        return QuoteTick(
            code=code,
            price=price,
            volume=volume,
            change_pct=change_pct,
            timestamp=timestamp,
            tr_id=tr_id,
        )

    def _log_control_frame(self, message: str) -> None:
        if not message.startswith("{"):
            return
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        tr_id = payload.get("header", {}).get("tr_id")
        message_text = payload.get("body", {}).get("msg1") or payload.get("msg1")
        if tr_id or message_text:
            logger.info("KIS websocket control frame: tr_id=%s msg=%s", tr_id, message_text)

    def _parse_tick_time(self, hhmmss: str) -> datetime:
        now = datetime.now(tz=KST)
        if len(hhmmss) != 6 or not hhmmss.isdigit():
            return now
        return now.replace(
            hour=int(hhmmss[0:2]),
            minute=int(hhmmss[2:4]),
            second=int(hhmmss[4:6]),
            microsecond=0,
        )

    def _normalize_codes(self, codes: list[str] | set[str]) -> set[str]:
        return {code.strip() for code in codes if code and code.strip()}

    def _to_int(self, value: str) -> int:
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return 0
        try:
            return abs(int(float(cleaned)))
        except ValueError:
            return 0

    def _to_float(self, value: str) -> float:
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
