"""Unit tests for the order safety gateway (P1-1).

Verifies that the kill switch + notional cap apply to live orders and are
correctly skipped for KIS PAPER (virtual) orders. Pure logic — no DB / broker.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.app.schemas.portfolio import OrderRequest, OrderType
from backend.app.services.automation import safety
from backend.app.services.orders.guard import (
    OrderBlocked,
    estimate_notional,
    guard_order,
    resolve_live_mode,
)
from shared.domain.account import AccountType, BrokerType
from shared.domain.trade import TradeDirection


@pytest.fixture(autouse=True)
def _reset_kill_switch():
    """safety._state is a process global — keep tests isolated."""
    safety.set_kill_switch(False)
    yield
    safety.set_kill_switch(False)


def _order(
    *,
    broker: BrokerType = BrokerType.KIS,
    account_type: AccountType = AccountType.REAL,
    price: str | None = "1000",
    quantity: int = 10,
    order_type: OrderType = OrderType.LIMIT,
) -> OrderRequest:
    return OrderRequest(
        broker=broker,
        account_type=account_type,
        stock_code="005930",
        direction=TradeDirection.BUY,
        quantity=quantity,
        order_type=order_type,
        price=Decimal(price) if price is not None else None,
    )


# --- resolve_live_mode -------------------------------------------------------

def test_resolve_live_mode_kis_paper_is_not_live():
    assert resolve_live_mode(BrokerType.KIS, AccountType.PAPER) is False


def test_resolve_live_mode_kis_real_and_isa_are_live():
    assert resolve_live_mode(BrokerType.KIS, AccountType.REAL) is True
    assert resolve_live_mode(BrokerType.KIS, AccountType.ISA) is True


def test_resolve_live_mode_toss_is_always_live():
    assert resolve_live_mode(BrokerType.TOSS, AccountType.PAPER) is True
    assert resolve_live_mode(BrokerType.TOSS, AccountType.REAL) is True


# --- estimate_notional -------------------------------------------------------

def test_estimate_notional_uses_limit_price():
    assert estimate_notional(price=Decimal("1000"), quantity=10) == Decimal("10000")


def test_estimate_notional_falls_back_to_reference_for_market_orders():
    assert estimate_notional(
        price=None, quantity=4, reference_price=Decimal("500")
    ) == Decimal("2000")
    # price of 0 (MARKET) also falls back to the reference price
    assert estimate_notional(
        price=Decimal("0"), quantity=3, reference_price=Decimal("100")
    ) == Decimal("300")


def test_estimate_notional_zero_when_no_price_known():
    assert estimate_notional(price=None, quantity=5) == Decimal("0")


# --- guard_order: kill switch ------------------------------------------------

def test_guard_blocks_live_order_when_kill_switch_on():
    safety.set_kill_switch(True, reason="test halt")
    with pytest.raises(OrderBlocked, match="kill switch"):
        guard_order(_order(account_type=AccountType.REAL))


def test_guard_allows_paper_order_even_with_kill_switch_on():
    safety.set_kill_switch(True, reason="test halt")
    # KIS PAPER is virtual money → not gated, must not raise.
    guard_order(_order(account_type=AccountType.PAPER))


def test_guard_blocks_market_order_when_kill_switch_on():
    # MARKET order (no price) → notional 0, but kill switch still applies.
    safety.set_kill_switch(True, reason="test halt")
    with pytest.raises(OrderBlocked):
        guard_order(_order(account_type=AccountType.REAL, price=None, order_type=OrderType.MARKET))


# --- guard_order: notional cap (AUTOMATION_MAX_ORDER_VALUE = 5,000,000) -------

def test_guard_blocks_live_order_above_notional_cap():
    # 1,000,000 x 10 = 10,000,000 > 5,000,000
    with pytest.raises(OrderBlocked, match="exceeds"):
        guard_order(_order(account_type=AccountType.REAL, price="1000000", quantity=10))


def test_guard_allows_live_order_within_notional_cap():
    # 100,000 x 10 = 1,000,000 < 5,000,000, kill switch off → allowed
    guard_order(_order(account_type=AccountType.REAL, price="100000", quantity=10))


def test_guard_allows_large_paper_order_ignoring_cap():
    # PAPER is not live → cap not enforced even for a huge notional.
    guard_order(_order(account_type=AccountType.PAPER, price="1000000", quantity=100))
