"""Daily realized-loss limit enforcement tests (previously a dead config).

AUTOMATION_MAX_DAILY_LOSS_PCT (-5.0 default) was stored in safety state but
enforced nowhere. assert_daily_loss_ok now blocks new BUY orders once today's
FIFO realized loss breaches the limit relative to the latest NAV snapshot.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from backend.app.services.orders.guard import OrderBlocked, assert_daily_loss_ok
from backend.app.services.performance.reconstruct import FilledTrade, realized_pnl_on
from shared.db.models import Account, PortfolioSnapshot, Trade
from shared.domain.account import AccountType, BrokerType
from shared.domain.trade import TradeDirection

TODAY = date.today()
EARLIER = TODAY - timedelta(days=10)


# --- realized_pnl_on (pure FIFO) ---------------------------------------------

def test_realized_pnl_counts_only_target_day():
    fills = [
        FilledTrade(EARLIER, "A", "BUY", 100, 10000.0),
        FilledTrade(TODAY, "A", "SELL", 100, 4000.0),
    ]
    assert realized_pnl_on(fills, TODAY) == pytest.approx(-600_000.0)
    assert realized_pnl_on(fills, EARLIER) == 0.0  # buys realize nothing


def test_realized_pnl_partial_fifo_and_fees():
    fills = [
        FilledTrade(EARLIER, "A", "BUY", 100, 100.0, fees=100.0),  # cost 101/sh
        FilledTrade(TODAY, "A", "SELL", 40, 110.0, fees=40.0),     # proceeds 109/sh
    ]
    assert realized_pnl_on(fills, TODAY) == pytest.approx((109.0 - 101.0) * 40)


def test_realized_pnl_ignores_sell_without_lot():
    fills = [FilledTrade(TODAY, "A", "SELL", 10, 100.0)]
    assert realized_pnl_on(fills, TODAY) == 0.0


# --- assert_daily_loss_ok ----------------------------------------------------

async def _seed(session, *, account: str, nav: float | None, sell_price: float):
    session.add(Account(type=account, app_key="x", app_secret="y", account_no="z"))
    if nav is not None:
        session.add(
            PortfolioSnapshot(
                account_type=account,
                date=TODAY - timedelta(days=1),
                nav=Decimal(str(nav)),
                cash=Decimal("0"),
                holdings_value=Decimal(str(nav)),
            )
        )
    session.add(
        Trade(
            account_type=account,
            stock_code="005930",
            direction="BUY",
            quantity=100,
            price=Decimal("10000"),
            executed_at=datetime.combine(EARLIER, datetime.min.time()),
            filled_quantity=100,
            filled_price=Decimal("10000"),
            filled_at=datetime.combine(EARLIER, datetime.min.time()),
            status="FILLED",
        )
    )
    session.add(
        Trade(
            account_type=account,
            stock_code="005930",
            direction="SELL",
            quantity=100,
            price=Decimal(str(sell_price)),
            executed_at=datetime.combine(TODAY, datetime.min.time()),
            filled_quantity=100,
            filled_price=Decimal(str(sell_price)),
            filled_at=datetime.combine(TODAY, datetime.min.time()),
            status="FILLED",
        )
    )
    await session.commit()


async def test_blocks_buy_after_breach(service_session):
    # Loss today = (4000-10000)*100 = -600k on NAV 10M = -6% <= -5% limit.
    await _seed(service_session, account="REAL", nav=10_000_000, sell_price=4000)
    with pytest.raises(OrderBlocked, match="Daily realized loss"):
        await assert_daily_loss_ok(
            service_session,
            broker=BrokerType.KIS,
            account_type=AccountType.REAL,
            direction=TradeDirection.BUY,
        )


async def test_sell_still_allowed_after_breach(service_session):
    await _seed(service_session, account="REAL", nav=10_000_000, sell_price=4000)
    await assert_daily_loss_ok(
        service_session,
        broker=BrokerType.KIS,
        account_type=AccountType.REAL,
        direction=TradeDirection.SELL,
    )


async def test_small_loss_allows_buy(service_session):
    # Loss = (9700-10000)*100 = -30k on 10M = -0.3% > -5% limit → allowed.
    await _seed(service_session, account="REAL", nav=10_000_000, sell_price=9700)
    await assert_daily_loss_ok(
        service_session,
        broker=BrokerType.KIS,
        account_type=AccountType.REAL,
        direction=TradeDirection.BUY,
    )


async def test_skipped_without_snapshot(service_session):
    # Same breach-sized loss but no NAV snapshot → reference unknown → skip.
    await _seed(service_session, account="REAL", nav=None, sell_price=4000)
    await assert_daily_loss_ok(
        service_session,
        broker=BrokerType.KIS,
        account_type=AccountType.REAL,
        direction=TradeDirection.BUY,
    )


async def test_paper_account_not_gated(service_session):
    await _seed(service_session, account="PAPER", nav=10_000_000, sell_price=4000)
    await assert_daily_loss_ok(
        service_session,
        broker=BrokerType.KIS,
        account_type=AccountType.PAPER,
        direction=TradeDirection.BUY,
    )
