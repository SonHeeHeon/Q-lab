"""Test kill-switch persistence to the settings table (P1-6).

In-memory SQLite (StaticPool) so save/load round-trips without a real DB.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.services.automation.store import load_kill_switch, save_kill_switch
from shared.db.models import ServiceBase


async def _make_sessionmaker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(ServiceBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_load_returns_none_when_never_set():
    engine, Session = await _make_sessionmaker()
    try:
        async with Session() as session:
            assert await load_kill_switch(session) is None
    finally:
        await engine.dispose()


async def test_save_then_load_roundtrip():
    engine, Session = await _make_sessionmaker()
    try:
        async with Session() as session:
            await save_kill_switch(session, enabled=True, reason="halt for maintenance")
        async with Session() as session:
            assert await load_kill_switch(session) == (True, "halt for maintenance")
    finally:
        await engine.dispose()


async def test_save_overwrites_and_clears_reason():
    engine, Session = await _make_sessionmaker()
    try:
        async with Session() as session:
            await save_kill_switch(session, enabled=True, reason="x")
        async with Session() as session:
            await save_kill_switch(session, enabled=False, reason=None)
        async with Session() as session:
            assert await load_kill_switch(session) == (False, None)
    finally:
        await engine.dispose()
