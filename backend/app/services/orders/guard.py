"""Unified order safety gateway.

Every order path (manual API, alert trigger, rebalancer, risk manager) must pass
through this gate before an order reaches a broker, so the automation kill switch
and per-order notional cap apply uniformly.

Previously the manual (``POST /api/portfolio/orders``) and alert-trigger paths
placed orders WITHOUT calling ``assert_order_allowed`` — a real-money order could
be submitted with the kill switch engaged or above the configured notional cap.
``guard_order`` closes that hole; rebalancer/risk-manager keep their existing
direct ``assert_order_allowed`` calls (already safe).
"""

from __future__ import annotations

import logging
from datetime import date as Date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.schemas.portfolio import OrderRequest
from backend.app.services.automation.safety import assert_order_allowed, get_safety_state
from shared.db.models import PortfolioSnapshot
from shared.domain.account import AccountType, BrokerType
from shared.domain.trade import TradeDirection

logger = logging.getLogger(__name__)


class OrderBlocked(Exception):
    """Raised when the safety gateway blocks an order before it reaches a broker."""


# 연금계좌: KIS 주문 TR(퇴직연금 전용 TR 여부) 미검증 — 검증 완료 전까지 주문
# 차단(자문 모드). 잔고/시세 조회는 막지 않는다.
ORDER_UNVERIFIED_ACCOUNT_TYPES = frozenset(
    {AccountType.DC, AccountType.IRP, AccountType.PENSION}
)


def resolve_live_mode(broker: BrokerType, account_type: AccountType) -> bool:
    """Whether an order risks real money and must pass the safety gate.

    KIS PAPER (모의) is a virtual account used for testing, so it is not gated.
    Everything else — KIS REAL/ISA and Toss — is treated as live so the kill
    switch always applies to real-money order attempts.
    """
    if broker is BrokerType.KIS and account_type is AccountType.PAPER:
        return False
    return True


def estimate_notional(
    *,
    price: Decimal | None,
    quantity: int,
    reference_price: Decimal | None = None,
) -> Decimal:
    """Best-effort order value in the order's own currency.

    Uses the limit price when present, else a caller-supplied reference (market)
    price for MARKET orders. Returns 0 when neither is known — the kill switch
    still applies regardless, only the notional cap is skipped.
    """
    unit = price if price and price > 0 else reference_price
    if unit is None or unit <= 0:
        return Decimal("0")
    return Decimal(unit) * Decimal(quantity)


def guard_order(
    request: OrderRequest,
    *,
    reference_price: Decimal | None = None,
) -> None:
    """Enforce the automation kill switch + notional cap for live orders.

    A no-op for KIS PAPER (virtual) orders. Raises ``OrderBlocked`` if the order
    must not proceed. This is the single choke point every order path calls.
    """
    if (
        request.broker is BrokerType.KIS
        and request.account_type in ORDER_UNVERIFIED_ACCOUNT_TYPES
    ):
        raise OrderBlocked(
            f"{request.account_type.value} 계좌는 주문 TR 미검증(자문 모드) — 실행 불가"
        )
    live_mode = resolve_live_mode(request.broker, request.account_type)
    notional = estimate_notional(
        price=request.price,
        quantity=request.quantity,
        reference_price=reference_price,
    )
    try:
        assert_order_allowed(estimated_notional=notional, live_mode=live_mode)
    except RuntimeError as exc:
        raise OrderBlocked(str(exc)) from exc


async def assert_daily_loss_ok(
    session: AsyncSession,
    *,
    broker: BrokerType,
    account_type: AccountType,
    direction: TradeDirection,
) -> None:
    """Enforce AUTOMATION_MAX_DAILY_LOSS_PCT: block new BUYs after the limit.

    Today's FIFO realized PnL (from filled trades) is compared against the most
    recent broker NAV snapshot. Once the realized loss breaches the configured
    percentage, further BUY orders are blocked for the day; SELLs stay allowed
    so positions can still be de-risked. Skipped when no NAV snapshot exists
    yet (the reference base would be a guess) or for non-live (KIS PAPER)
    orders. This limit was previously configured but enforced nowhere.
    """
    if direction is not TradeDirection.BUY:
        return
    if not resolve_live_mode(broker, account_type):
        return

    # Imported here: performance.service imports broker-facing modules that the
    # guard's synchronous callers (tests included) should not pay for.
    from backend.app.services.performance.service import _load_filled_trades
    from backend.app.services.performance.reconstruct import realized_pnl_on

    today = Date.today()
    reference_nav = await _latest_snapshot_nav(session, account_type, today)
    if reference_nav is None or reference_nav <= 0:
        logger.debug(
            "daily-loss check skipped (no NAV snapshot) account=%s",
            account_type.value,
        )
        return

    fills = await _load_filled_trades(session, account_type)
    pnl_today = realized_pnl_on(fills, today)
    loss_pct = pnl_today / reference_nav * 100.0
    limit_pct = float(get_safety_state().max_daily_loss_pct)
    if loss_pct <= limit_pct:
        raise OrderBlocked(
            "Daily realized loss limit reached: "
            f"{loss_pct:.2f}% <= {limit_pct:.2f}% (new BUY orders blocked today)"
        )


async def _latest_snapshot_nav(
    session: AsyncSession,
    account_type: AccountType,
    as_of: Date,
) -> float | None:
    result = await session.execute(
        select(PortfolioSnapshot.nav)
        .where(PortfolioSnapshot.account_type == account_type.value)
        .where(PortfolioSnapshot.date <= as_of)
        .order_by(PortfolioSnapshot.date.desc())
        .limit(1)
    )
    nav = result.scalar_one_or_none()
    return float(nav) if nav is not None else None
