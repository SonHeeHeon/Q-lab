"""Shared pytest fixtures for the backend suite.

Implemented:
    - service_sessionmaker : in-memory SQLite (StaticPool) async_sessionmaker
                             with the full service schema created.
    - service_session      : a single AsyncSession from that maker.

These let tests exercise DB logic (and endpoint functions that take a session)
without touching the real service.db. Broker/LLM/WS mocks remain per-test.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from shared.db.models import ServiceBase


@pytest_asyncio.fixture
async def service_sessionmaker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(ServiceBase.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def service_session(service_sessionmaker):
    async with service_sessionmaker() as session:
        yield session
