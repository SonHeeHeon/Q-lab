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

from decimal import Decimal

from backend.app.schemas.portfolio import OrderRequest
from backend.app.services.automation.safety import assert_order_allowed
from shared.domain.account import AccountType, BrokerType


class OrderBlocked(Exception):
    """Raised when the safety gateway blocks an order before it reaches a broker."""


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
