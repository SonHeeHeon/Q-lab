"""Test the alert claim guard against double-firing (P1-3).

Uses an in-memory SQLite DB (shared via StaticPool) so the conditional-UPDATE
claim can be exercised end-to-end.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.services.alerts.monitor import _claim_alert
from shared.db.models import Alert, ServiceBase


async def _make_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(ServiceBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_claim_alert_single_winner_then_rejects_second():
    engine, Session = await _make_session()
    try:
        async with Session() as session:
            session.add(
                Alert(stock_code="005930", condition="PRICE_ABOVE", threshold=70000.0)
            )
            await session.commit()
            alert_id = (
                await session.execute(select(Alert.id))
            ).scalar_one()

            now = datetime.now().astimezone()
            first = await _claim_alert(session, alert_id, now)
            second = await _claim_alert(session, alert_id, now)

            assert first is True  # winner claims the alert
            assert second is False  # already triggered -> rejected (no double-fire)

            row = (
                await session.execute(
                    select(Alert.triggered_at).where(Alert.id == alert_id)
                )
            ).scalar_one()
            assert row is not None  # triggered_at persisted
    finally:
        await engine.dispose()


async def test_claim_alert_missing_id_returns_false():
    engine, Session = await _make_session()
    try:
        async with Session() as session:
            claimed = await _claim_alert(session, 9999, datetime.now().astimezone())
            assert claimed is False
    finally:
        await engine.dispose()
