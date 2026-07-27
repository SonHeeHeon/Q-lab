"""Backend tax wrapper tests: backend/app/services/tax/kr.py.

``ytd_taxable_etf_gain`` seeds filled trades into the in-memory
``service_sessionmaker`` DB (mirrors test_performance_service.py's seeding
style) and checks only 과세대상(etf_taxable) ETF gains are summed — domestic-
equity ETF and stock gains must be excluded. ``realized_pnl_between`` window
edges are covered directly against the pure reconstruct helper.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from backend.app.services.performance.reconstruct import FilledTrade, realized_pnl_between
from backend.app.services.tax import kr as tax_kr
from shared.db.models import Account, Trade
from shared.domain.account import AccountType


# --- realized_pnl_between window edges -------------------------------------------

def test_realized_pnl_between_inclusive_edges_and_code_filter():
    trades = [
        FilledTrade(date=date(2026, 1, 1), code="A", side="BUY", qty=10, price=100.0),
        FilledTrade(date=date(2026, 1, 10), code="A", side="SELL", qty=5, price=150.0),  # before window
        FilledTrade(date=date(2026, 6, 1), code="A", side="SELL", qty=3, price=200.0),  # start edge
        FilledTrade(date=date(2026, 12, 31), code="A", side="SELL", qty=2, price=120.0),  # end edge
        FilledTrade(date=date(2026, 6, 15), code="B", side="BUY", qty=10, price=50.0),
        FilledTrade(date=date(2026, 6, 20), code="B", side="SELL", qty=10, price=80.0),
    ]

    # Both edges included: (200-100)*3 + (120-100)*2 = 600 + 40 = 340 for A,
    # plus (80-50)*10 = 300 for B.
    total = realized_pnl_between(trades, date(2026, 6, 1), date(2026, 12, 31))
    assert total == pytest.approx(340.0 + 300.0)

    # code_filter restricts to A only.
    a_only = realized_pnl_between(
        trades, date(2026, 6, 1), date(2026, 12, 31), code_filter={"A"}
    )
    assert a_only == pytest.approx(340.0)

    # Narrowing the end edge by one day excludes the 12/31 sell.
    excl_end = realized_pnl_between(
        trades, date(2026, 6, 1), date(2026, 12, 30), code_filter={"A"}
    )
    assert excl_end == pytest.approx(300.0)

    # Narrowing the start edge by one day excludes the 6/1 sell.
    excl_start = realized_pnl_between(
        trades, date(2026, 6, 2), date(2026, 12, 31), code_filter={"A"}
    )
    assert excl_start == pytest.approx(40.0)


# --- ytd_taxable_etf_gain ----------------------------------------------------------

async def _seed_round_trip(
    session,
    *,
    code: str,
    buy_price: str,
    sell_price: str,
    qty: int = 10,
    buy_day: datetime,
    sell_day: datetime,
    account_type: str = "PAPER",
) -> None:
    session.add_all(
        [
            Trade(
                account_type=account_type,
                stock_code=code,
                direction="BUY",
                quantity=qty,
                price=Decimal(buy_price),
                executed_at=buy_day,
                filled_quantity=qty,
                filled_price=Decimal(buy_price),
                filled_at=buy_day,
                status="FILLED",
            ),
            Trade(
                account_type=account_type,
                stock_code=code,
                direction="SELL",
                quantity=qty,
                price=Decimal(sell_price),
                executed_at=sell_day,
                filled_quantity=qty,
                filled_price=Decimal(sell_price),
                filled_at=sell_day,
                status="FILLED",
            ),
        ]
    )


async def test_ytd_taxable_etf_gain_excludes_domestic_equity_and_stock(
    service_sessionmaker,
):
    async with service_sessionmaker() as session:
        session.add(Account(type="PAPER", app_key="x", app_secret="y", account_no="z"))

        # Taxable ETF (KODEX 인버스): +10,000 * 10 gain -> counted.
        await _seed_round_trip(
            session,
            code="114800",
            buy_price="10000",
            sell_price="11000",
            buy_day=datetime(2026, 2, 1, 9, 0),
            sell_day=datetime(2026, 3, 1, 9, 0),
        )
        # Domestic-equity ETF (KODEX 200): gain but tax-free class -> excluded.
        await _seed_round_trip(
            session,
            code="069500",
            buy_price="30000",
            sell_price="35000",
            buy_day=datetime(2026, 2, 1, 9, 0),
            sell_day=datetime(2026, 4, 1, 9, 0),
        )
        # Plain stock: gain but not an ETF -> excluded.
        await _seed_round_trip(
            session,
            code="005930",
            buy_price="60000",
            sell_price="70000",
            buy_day=datetime(2026, 2, 1, 9, 0),
            sell_day=datetime(2026, 5, 1, 9, 0),
        )
        await session.commit()

    async with service_sessionmaker() as session:
        gain = await tax_kr.ytd_taxable_etf_gain(session, [AccountType.PAPER], 2026)

    assert gain == pytest.approx((11000 - 10000) * 10)


async def test_ytd_taxable_etf_gain_zero_when_no_taxable_etf_trades(
    service_sessionmaker,
):
    async with service_sessionmaker() as session:
        session.add(Account(type="PAPER", app_key="x", app_secret="y", account_no="z"))
        await _seed_round_trip(
            session,
            code="005930",
            buy_price="60000",
            sell_price="70000",
            buy_day=datetime(2026, 2, 1, 9, 0),
            sell_day=datetime(2026, 5, 1, 9, 0),
        )
        await session.commit()

    async with service_sessionmaker() as session:
        gain = await tax_kr.ytd_taxable_etf_gain(session, [AccountType.PAPER], 2026)

    assert gain == 0.0


async def test_ytd_taxable_etf_gain_excludes_sells_outside_year(service_sessionmaker):
    async with service_sessionmaker() as session:
        session.add(Account(type="PAPER", app_key="x", app_secret="y", account_no="z"))
        # Sell falls in the following year -> outside the requested YTD window.
        await _seed_round_trip(
            session,
            code="114800",
            buy_price="10000",
            sell_price="11000",
            buy_day=datetime(2026, 12, 1, 9, 0),
            sell_day=datetime(2027, 1, 5, 9, 0),
        )
        await session.commit()

    async with service_sessionmaker() as session:
        gain = await tax_kr.ytd_taxable_etf_gain(session, [AccountType.PAPER], 2026)

    assert gain == 0.0
