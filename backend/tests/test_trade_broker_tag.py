"""등급 T4: trades.broker 배선 회귀 테스트.

Toss 주문은 order.account_type이 항상 None이라 기존 코드가
request.account_type(default PAPER)로 폴백해 KIS 모의 계좌와 충돌했다.
_persist_trade_skeleton이 broker를 정확히 태깅하고, Toss는 account_type을
PAPER로 폴백하지 않는지 in-memory service DB로 검증한다. 실제 data/*.db는
건드리지 않는다 — 전부 in-memory SQLite(``service_sessionmaker``)로 돈다.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from backend.app.api.portfolio import _persist_trade_skeleton
from backend.app.schemas.portfolio import OrderRequest, OrderResponse, OrderType
from shared.db.models import Trade
from shared.domain.account import AccountType, BrokerType
from shared.domain.trade import TradeDirection


def _order_request(**overrides) -> OrderRequest:
    payload = dict(
        broker=BrokerType.KIS,
        account_type=AccountType.PAPER,
        stock_code="005930",
        direction=TradeDirection.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        price=Decimal("70000"),
    )
    payload.update(overrides)
    return OrderRequest.model_validate(payload)


def _order_response(**overrides) -> OrderResponse:
    payload = dict(
        broker=BrokerType.KIS,
        account_type=AccountType.PAPER,
        stock_code="005930",
        direction=TradeDirection.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        price=Decimal("70000"),
        kis_order_no="ORDER-1",
        accepted_at=datetime(2026, 7, 27, 9, 0, 0),
        raw={},
    )
    payload.update(overrides)
    return OrderResponse.model_validate(payload)


async def test_kis_order_tags_broker_kis_and_keeps_account_type(service_session):
    order = _order_response(broker=BrokerType.KIS, account_type=AccountType.PAPER)
    request = _order_request(broker=BrokerType.KIS, account_type=AccountType.PAPER)

    result = await _persist_trade_skeleton(service_session, order, request)
    assert result.persisted

    trade = await service_session.get(Trade, result.trade_id)
    assert trade.broker == "KIS"
    assert trade.account_type == "PAPER"


async def test_toss_order_tags_broker_toss_and_does_not_default_to_paper(
    service_session,
):
    # Toss OrderResponse always carries account_type=None (see
    # TossRestClient.place_order) — request.account_type defaults to PAPER,
    # but that must NOT leak onto the persisted Toss trade.
    order = _order_response(
        broker=BrokerType.TOSS,
        account_type=None,
        kis_order_no=None,
        broker_order_no="TOSS-ORDER-1",
    )
    request = _order_request(broker=BrokerType.TOSS)

    result = await _persist_trade_skeleton(service_session, order, request)
    assert result.persisted

    trade = await service_session.get(Trade, result.trade_id)
    assert trade.broker == "TOSS"
    assert trade.account_type is None
    assert trade.account_type != "PAPER"


async def test_no_stray_toss_account_row_created(service_session):
    """Toss persistence must not create a placeholder KIS-style Account row."""
    order = _order_response(
        broker=BrokerType.TOSS,
        account_type=None,
        kis_order_no=None,
        broker_order_no="TOSS-ORDER-2",
    )
    request = _order_request(broker=BrokerType.TOSS)

    await _persist_trade_skeleton(service_session, order, request)

    from shared.db.models import Account

    accounts = (await service_session.execute(select(Account))).scalars().all()
    assert accounts == []
