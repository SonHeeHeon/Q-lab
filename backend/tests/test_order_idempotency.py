"""Backend idempotency net for order placement (P1-2).

A retried order submission carrying the same client_order_id must be
deduplicated instead of placing a second real order. In-memory SQLite verifies
the lookup + the unique constraint (NULLs stay unaffected).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.api.portfolio import _find_trade_by_client_order_id
from backend.app.schemas.portfolio import OrderRequest
from shared.db.models import Account, ServiceBase, Trade
from shared.domain.trade import TradeDirection


async def _make_sessionmaker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(ServiceBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _trade(client_order_id: str | None, code: str = "005930") -> Trade:
    return Trade(
        account_type="PAPER",
        stock_code=code,
        direction="BUY",
        quantity=1,
        price=Decimal("1000"),
        executed_at=datetime.now().astimezone(),
        client_order_id=client_order_id,
    )


def test_order_request_accepts_client_order_id():
    req = OrderRequest(
        stock_code="005930",
        direction=TradeDirection.BUY,
        quantity=1,
        price=Decimal("1000"),
        client_order_id="abc-1",
    )
    assert req.client_order_id == "abc-1"


def test_order_request_client_order_id_optional():
    req = OrderRequest(
        stock_code="005930",
        direction=TradeDirection.BUY,
        quantity=1,
        price=Decimal("1000"),
    )
    assert req.client_order_id is None


async def test_find_trade_by_client_order_id():
    engine, Session = await _make_sessionmaker()
    try:
        async with Session() as session:
            session.add(Account(type="PAPER", app_key="x", app_secret="y", account_no="z"))
            session.add(_trade("key-123"))
            await session.commit()

            found = await _find_trade_by_client_order_id(session, "key-123")
            assert found is not None
            assert found.client_order_id == "key-123"
            assert await _find_trade_by_client_order_id(session, "missing") is None
    finally:
        await engine.dispose()


async def test_client_order_id_unique_constraint():
    engine, Session = await _make_sessionmaker()
    try:
        async with Session() as session:
            session.add(Account(type="PAPER", app_key="x", app_secret="y", account_no="z"))
            session.add(_trade("dup", code="A"))
            await session.commit()
        with pytest.raises(IntegrityError):
            async with Session() as session:
                session.add(_trade("dup", code="B"))
                await session.commit()
    finally:
        await engine.dispose()


async def test_null_client_order_ids_are_allowed():
    engine, Session = await _make_sessionmaker()
    try:
        async with Session() as session:
            session.add(Account(type="PAPER", app_key="x", app_secret="y", account_no="z"))
            session.add(_trade(None, code="A"))
            session.add(_trade(None, code="B"))
            await session.commit()  # two NULL keys must not violate the unique index
    finally:
        await engine.dispose()
