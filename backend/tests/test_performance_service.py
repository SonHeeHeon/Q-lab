"""End-to-end test for the performance service reconstruction (P1-8 coverage).

Seeds an in-memory service DB (accounts + filled trades) and research DB
(stocks + prices_daily), then verifies load_account_performance reconstructs a
sensible equity curve when no broker snapshots exist.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.services.performance.service import load_account_performance
from shared.db.models import (
    Account,
    PriceDaily,
    ResearchBase,
    ServiceBase,
    Stock,
    Trade,
)
from shared.domain.account import AccountType


async def _engines():
    def _engine():
        return create_async_engine(
            "sqlite+aiosqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )

    svc, res = _engine(), _engine()
    async with svc.begin() as conn:
        await conn.run_sync(ServiceBase.metadata.create_all)
    async with res.begin() as conn:
        await conn.run_sync(ResearchBase.metadata.create_all)
    return (
        svc,
        res,
        async_sessionmaker(svc, expire_on_commit=False),
        async_sessionmaker(res, expire_on_commit=False),
    )


async def test_reconstructs_curve_from_trades_and_prices():
    svc, res, Svc, Res = await _engines()
    try:
        async with Res() as session:
            session.add(
                Stock(code="005930", name="삼성전자", market="KOSPI", listed_at=date(2000, 1, 1))
            )
            for day, close in [
                (date(2026, 1, 2), 70000),
                (date(2026, 1, 5), 72000),
                (date(2026, 1, 6), 71000),
            ]:
                session.add(
                    PriceDaily(
                        stock_code="005930",
                        date=day,
                        open=close,
                        high=close,
                        low=close,
                        close=close,
                        volume=1000,
                    )
                )
            await session.commit()

        async with Svc() as session:
            session.add(Account(type="PAPER", app_key="x", app_secret="y", account_no="z"))
            session.add(
                Trade(
                    account_type="PAPER",
                    stock_code="005930",
                    direction="BUY",
                    quantity=10,
                    price=Decimal("70000"),
                    executed_at=datetime(2026, 1, 2, 9, 0),
                    filled_quantity=10,
                    filled_price=Decimal("70000"),
                    filled_at=datetime(2026, 1, 2, 9, 1),
                    status="FILLED",
                )
            )
            await session.commit()

        async with Svc() as ss, Res() as rs:
            perf = await load_account_performance(
                ss,
                rs,
                account_type=AccountType.PAPER,
                strategy="value_v1",
                initial_capital=1_000_000,
            )

        assert perf.source == "RECONSTRUCTED"
        assert perf.mode == "PAPER"
        assert len(perf.equity_curve) == 3  # three price dates
        navs = [nav for _, nav in perf.equity_curve]
        # Start 1,000,000 (300k cash + 10*70000), rises with price, dips 1/6.
        assert navs[0] == 1_000_000
        assert navs[1] > navs[0]
        assert navs[2] < navs[1]
        assert perf.metrics.n_trades == 1
        assert perf.warnings  # reconstruction caveat present
    finally:
        await svc.dispose()
        await res.dispose()


async def test_empty_performance_when_no_trades():
    svc, res, Svc, Res = await _engines()
    try:
        async with Svc() as ss, Res() as rs:
            perf = await load_account_performance(
                ss, rs, account_type=AccountType.REAL, strategy="value_v1"
            )
        assert perf.source == "EMPTY"
        assert perf.equity_curve == []
    finally:
        await svc.dispose()
        await res.dispose()
