"""Real-time portfolio risk guard fed by KIS quote ticks."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from backend.app.core.config import settings
from backend.app.schemas.portfolio import OrderRequest, OrderResponse, OrderType
from backend.app.services.kis.rest_client import KISRestClient, KISRestError
from backend.app.services.kis.ws_client import QuoteTick
from backend.app.services.notify.telegram import TelegramSendError, send_markdown
from shared.domain.account import AccountType
from shared.domain.trade import TradeDirection

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RiskPosition:
    stock_code: str
    quantity: int
    avg_buy_price: Decimal


@dataclass(frozen=True, slots=True)
class RiskAction:
    account_type: AccountType
    stock_code: str
    quantity: int
    tick_price: Decimal
    avg_buy_price: Decimal
    pnl_pct: Decimal
    stop_loss_pct: Decimal
    is_mock: bool
    order_response: OrderResponse | None = None


class PortfolioRiskManager:
    """Stops out tracked positions when real-time ticks breach the threshold."""

    def __init__(
        self,
        *,
        account_type: AccountType | None = None,
        kis_client: KISRestClient | None = None,
        stop_loss_pct: Decimal | float | None = None,
        is_mock: bool | None = None,
        refresh_seconds: int | None = None,
    ) -> None:
        self.account_type = account_type or settings.RISK_MANAGER_ACCOUNT_TYPE
        self._kis_client = kis_client or KISRestClient()
        self._stop_loss_pct = Decimal(
            str(stop_loss_pct if stop_loss_pct is not None else settings.RISK_MANAGER_STOP_LOSS_PCT)
        )
        self._is_mock = settings.RISK_MANAGER_IS_MOCK if is_mock is None else is_mock
        self._refresh_seconds = refresh_seconds or settings.RISK_MANAGER_POSITION_REFRESH_SECONDS
        self._positions: dict[str, RiskPosition] = {}
        self._triggered_codes: set[str] = set()
        self._last_refresh_at: datetime | None = None
        self._lock = asyncio.Lock()

    @property
    def tracked_codes(self) -> set[str]:
        return set(self._positions)

    async def refresh_positions(self) -> set[str]:
        """Refresh tracked holdings from KIS balance."""

        portfolio = await self._kis_client.get_balance(self.account_type)
        positions: dict[str, RiskPosition] = {}
        for position in portfolio.positions:
            if position.quantity <= 0 or position.avg_buy_price <= 0:
                continue
            code = position.stock_code.zfill(6)
            positions[code] = RiskPosition(
                stock_code=code,
                quantity=position.quantity,
                avg_buy_price=position.avg_buy_price,
            )
        self._positions = positions
        self._last_refresh_at = datetime.now()
        logger.info(
            "risk manager refreshed positions account=%s codes=%s",
            self.account_type.value,
            sorted(self._positions),
        )
        return set(self._positions)

    async def handle_tick(self, tick: QuoteTick) -> RiskAction | None:
        """Inspect one tick and execute a stop-loss action if needed."""

        await self._refresh_if_stale()
        position = self._positions.get(tick.code.zfill(6))
        if position is None or position.stock_code in self._triggered_codes:
            return None
        tick_price = Decimal(str(tick.price))
        pnl_pct = (tick_price / position.avg_buy_price - Decimal("1")) * Decimal("100")
        if pnl_pct > self._stop_loss_pct:
            return None

        async with self._lock:
            if position.stock_code in self._triggered_codes:
                return None
            self._triggered_codes.add(position.stock_code)
            try:
                return await self._execute_stop_loss(position, tick_price, pnl_pct)
            except Exception:
                self._triggered_codes.discard(position.stock_code)
                raise

    async def _refresh_if_stale(self) -> None:
        if self._last_refresh_at is None:
            await self.refresh_positions()
            return
        if datetime.now() - self._last_refresh_at > timedelta(seconds=self._refresh_seconds):
            await self.refresh_positions()

    async def _execute_stop_loss(
        self,
        position: RiskPosition,
        tick_price: Decimal,
        pnl_pct: Decimal,
    ) -> RiskAction:
        request = OrderRequest(
            account_type=self.account_type,
            stock_code=position.stock_code,
            direction=TradeDirection.SELL,
            quantity=position.quantity,
            order_type=OrderType.MARKET,
            price=None,
        )
        order_response: OrderResponse | None = None
        if self._is_mock:
            logger.warning(
                "risk manager mock stop-loss account=%s code=%s qty=%s pnl_pct=%s threshold=%s",
                self.account_type.value,
                position.stock_code,
                position.quantity,
                pnl_pct,
                self._stop_loss_pct,
            )
        else:
            try:
                order_response = await self._kis_client.place_order(request)
            except KISRestError:
                logger.exception(
                    "risk manager stop-loss order failed account=%s code=%s",
                    self.account_type.value,
                    position.stock_code,
                )
                raise

        action = RiskAction(
            account_type=self.account_type,
            stock_code=position.stock_code,
            quantity=position.quantity,
            tick_price=tick_price,
            avg_buy_price=position.avg_buy_price,
            pnl_pct=pnl_pct,
            stop_loss_pct=self._stop_loss_pct,
            is_mock=self._is_mock,
            order_response=order_response,
        )
        await self._notify_stop_loss(action)
        return action

    async def _notify_stop_loss(self, action: RiskAction) -> None:
        mode = "MOCK" if action.is_mock else "LIVE"
        order_no = action.order_response.kis_order_no if action.order_response else "-"
        text = (
            f"[긴급] {action.stock_code} 리스크 관리(손절) 자동 매도 완료\n"
            f"- 모드: {mode}\n"
            f"- 계좌: {action.account_type.value}\n"
            f"- 수량: {action.quantity}\n"
            f"- 현재가: {action.tick_price}\n"
            f"- 평균단가: {action.avg_buy_price}\n"
            f"- 손익률: {action.pnl_pct:.2f}%\n"
            f"- 주문번호: {order_no}"
        )
        try:
            await send_markdown(text)
        except TelegramSendError:
            logger.exception("risk manager Telegram notification failed")
