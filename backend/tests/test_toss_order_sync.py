"""등급 T5a: Toss 주문 체결 동기화 + trade-journal broker 배선 회귀 테스트.

실제 data/*.db와 실제 Toss API는 절대 건드리지 않는다 — 전부 in-memory
service DB(``service_sessionmaker``)와 fake Toss client(``_request`` 오버라이드)로 검증한다.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from backend.app.api.trade_journal import _trade_response
from backend.app.services.batch.toss_order_sync import sync_toss_orders_once
from backend.app.services.toss.rest_client import TossRestClient
from shared.db.models import Trade


class FakeTossOrderClient(TossRestClient):
    """Fake Toss client returning canned /api/v1/orders payloads by status group."""

    def __init__(self, orders_by_status: dict[str, list[dict]]) -> None:
        super().__init__(client_id="client", client_secret="secret", account_seq=1)
        self._orders_by_status = orders_by_status
        self.calls: list[tuple[str, dict]] = []

    async def _request(self, method, path, **kwargs):  # noqa: ANN001
        if path == "/api/v1/orders":
            params = kwargs.get("params") or {}
            self.calls.append((method, params))
            status = params.get("status")
            rows = self._orders_by_status.get(status, [])
            return {"result": {"orders": rows, "nextCursor": None, "hasNext": False}}
        raise AssertionError((method, path, kwargs))


EXISTING_ORDER_ROW = {
    "orderId": "TOSS-ORDER-EXISTING",
    "symbol": "005930",
    "side": "BUY",
    "orderType": "LIMIT",
    "timeInForce": "DAY",
    "status": "FILLED",
    "price": "70000",
    "quantity": "10",
    "orderAmount": None,
    "currency": "KRW",
    "orderedAt": "2026-07-20T09:00:00+09:00",
    "canceledAt": None,
    "execution": {
        "filledQuantity": "10",
        "averageFilledPrice": "70000",
        "filledAmount": "700000",
        "commission": "1400",
        "tax": "0",
        "filledAt": "2026-07-20T09:31:15+09:00",
        "settlementDate": "2026-07-22",
    },
}

NEW_ORDER_ROW = {
    "orderId": "TOSS-ORDER-NEW",
    "symbol": "AAPL",
    "side": "SELL",
    "orderType": "LIMIT",
    "timeInForce": "DAY",
    "status": "PARTIAL_FILLED",
    "price": "185.5",
    "quantity": "5",
    "orderAmount": None,
    "currency": "USD",
    "orderedAt": "2026-07-20T10:00:00+09:00",
    "canceledAt": None,
    "execution": {
        "filledQuantity": "2",
        "averageFilledPrice": "185.25",
        "filledAmount": "370.5",
        "commission": "0.5",
        "tax": "0",
        "filledAt": "2026-07-20T10:00:05+09:00",
        "settlementDate": None,
    },
}


async def test_sync_updates_existing_and_inserts_new_toss_trade(service_sessionmaker):
    async with service_sessionmaker() as session:
        session.add(
            Trade(
                broker="TOSS",
                account_type=None,
                stock_code="005930",
                direction="BUY",
                quantity=10,
                price=Decimal("70000"),
                executed_at=datetime(2026, 7, 20, 9, 0, 0),
                kis_order_no="TOSS-ORDER-EXISTING",
                status="PENDING",
                filled_quantity=0,
                fees=Decimal("0"),
                taxes=Decimal("0"),
            )
        )
        await session.commit()

    client = FakeTossOrderClient({"OPEN": [], "CLOSED": [EXISTING_ORDER_ROW, NEW_ORDER_ROW]})

    result = await sync_toss_orders_once(session_factory=service_sessionmaker, client=client)

    assert result.imported == 1
    assert result.updated == 1
    assert result.skipped == 0
    assert len(result.trade_ids) == 2

    async with service_sessionmaker() as session:
        rows = (await session.execute(select(Trade).order_by(Trade.id))).scalars().all()
        assert len(rows) == 2

        existing = next(t for t in rows if t.kis_order_no == "TOSS-ORDER-EXISTING")
        assert existing.broker == "TOSS"
        assert existing.status == "FILLED"
        assert existing.filled_quantity == 10
        assert existing.filled_price == Decimal("70000")
        assert existing.fees == Decimal("1400")
        assert existing.taxes == Decimal("0")
        assert existing.filled_at is not None

        new_trade = next(t for t in rows if t.kis_order_no == "TOSS-ORDER-NEW")
        assert new_trade.broker == "TOSS"
        assert new_trade.account_type is None
        assert new_trade.stock_code == "AAPL"
        assert new_trade.direction == "SELL"
        assert new_trade.quantity == 5
        assert new_trade.filled_quantity == 2
        assert new_trade.filled_price == Decimal("185.25")
        assert new_trade.fees == Decimal("0.5")
        assert new_trade.status == "PARTIAL_FILLED"

    # Idempotent re-run: same orderIds already present locally -> no new inserts.
    result2 = await sync_toss_orders_once(session_factory=service_sessionmaker, client=client)
    assert result2.imported == 0
    assert result2.updated == 2

    async with service_sessionmaker() as session:
        rows = (await session.execute(select(Trade))).scalars().all()
        assert len(rows) == 2


async def test_sync_skips_non_configured_client(service_sessionmaker):
    client = TossRestClient(client_id="", client_secret="")

    result = await sync_toss_orders_once(session_factory=service_sessionmaker, client=client)

    assert result.imported == 0
    assert result.updated == 0
    assert result.notes == ["Toss client is not configured; skipped"]


def test_journal_serializes_toss_trade_with_null_account_type():
    trade = Trade(
        id=1,
        broker="TOSS",
        account_type=None,
        stock_code="AAPL",
        direction="SELL",
        quantity=5,
        price=Decimal("185.25"),
        executed_at=datetime(2026, 7, 20, 10, 0, 5),
        kis_order_no="TOSS-ORDER-NEW",
        status="PARTIAL_FILLED",
        filled_quantity=2,
        filled_price=Decimal("185.25"),
        fees=Decimal("0.5"),
        taxes=Decimal("0"),
        filled_at=datetime(2026, 7, 20, 10, 0, 5),
    )

    response = _trade_response(trade)

    assert response.broker == "TOSS"
    assert response.account_type is None
    assert response.stock_code == "AAPL"
