"""Test the NAV snapshot upsert core (P1-6 performance go-forward).

In-memory SQLite verifies insert + on-conflict update on (account_type, date).
The live broker-balance path in run_nav_snapshot is exercised in production.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.services.batch.record_nav_snapshot import upsert_snapshot
from shared.db.models import PortfolioSnapshot, ServiceBase


async def _make_sessionmaker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(ServiceBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_upsert_inserts_then_updates_same_key():
    engine, Session = await _make_sessionmaker()
    day = date(2026, 7, 6)
    try:
        async with Session() as session:
            await upsert_snapshot(
                session,
                account_type="PAPER",
                as_of=day,
                nav=Decimal("100"),
                cash=Decimal("20"),
                holdings_value=Decimal("80"),
            )
            await session.commit()

        async with Session() as session:
            row = (await session.execute(select(PortfolioSnapshot))).scalar_one()
            assert row.account_type == "PAPER"
            assert float(row.nav) == 100.0
            assert row.source == "BROKER"

        # Same (account_type, date) -> update, not a duplicate row.
        async with Session() as session:
            await upsert_snapshot(
                session,
                account_type="PAPER",
                as_of=day,
                nav=Decimal("150"),
                cash=Decimal("30"),
                holdings_value=Decimal("120"),
            )
            await session.commit()

        async with Session() as session:
            rows = (await session.execute(select(PortfolioSnapshot))).scalars().all()
            assert len(rows) == 1
            assert float(rows[0].nav) == 150.0
            assert float(rows[0].holdings_value) == 120.0
    finally:
        await engine.dispose()


async def test_upsert_distinct_dates_coexist():
    engine, Session = await _make_sessionmaker()
    try:
        async with Session() as session:
            await upsert_snapshot(
                session, account_type="PAPER", as_of=date(2026, 7, 6),
                nav=Decimal("100"), cash=Decimal("0"), holdings_value=Decimal("100"),
            )
            await upsert_snapshot(
                session, account_type="PAPER", as_of=date(2026, 7, 7),
                nav=Decimal("110"), cash=Decimal("0"), holdings_value=Decimal("110"),
            )
            await session.commit()
        async with Session() as session:
            rows = (await session.execute(select(PortfolioSnapshot))).scalars().all()
            assert len(rows) == 2
    finally:
        await engine.dispose()
