"""Proposals API tests (Phase 4.2-B3): 승인 원자성 · 안전 차단 · 멱등 재시도."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

import backend.app.api.proposals as papi
from backend.app.schemas.portfolio import OrderResponse, OrderType
from backend.app.services.automation import safety
from shared.db.models import OrderProposal, Trade
from shared.domain.account import AccountType, BrokerType
from shared.domain.trade import TradeDirection


class FakeKis:
    def __init__(self, *, fail: bool = False):
        self.calls: list = []
        self.fail = fail

    async def place_order(self, request):
        if self.fail:
            raise AssertionError("broker must not be called in this scenario")
        self.calls.append(request)
        return OrderResponse(
            broker=BrokerType.KIS,
            account_type=request.account_type,
            stock_code=request.stock_code,
            direction=request.direction,
            quantity=request.quantity,
            order_type=OrderType.LIMIT,
            price=request.price,
            kis_order_no="KIS123",
            accepted_at=datetime.now(),
            raw={},
        )


async def _seed(session, **overrides) -> int:
    payload = dict(
        batch_id="batch1",
        proposal_date=date(2026, 7, 13),
        account_type="PAPER",
        strategy_name="qlab_alpha_v2",
        stock_code="005930",
        side="SELL",
        qty=3,
        order_type="LIMIT",
        limit_price=Decimal("70000"),
        last_price=Decimal("70210"),
        reason_json='{"rule": "BAND_TRIM"}',
        status="PROPOSED",
    )
    payload.update(overrides)
    row = OrderProposal(**payload)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row.id


@pytest.fixture(autouse=True)
def _kill_switch_off():
    safety.set_kill_switch(False)
    yield
    safety.set_kill_switch(False)


async def test_approve_happy_path_submits_once(service_session):
    pid = await _seed(service_session)
    fake = FakeKis()
    envelope = await papi.approve_proposal(
        pid, BackgroundTasks(), service_session, fake
    )
    assert envelope.error is None
    assert envelope.data.trade_id is not None
    assert len(fake.calls) == 1
    request = fake.calls[0]
    assert request.client_order_id  # 멱등키 발급됨
    assert request.direction is TradeDirection.SELL

    row = await service_session.get(OrderProposal, pid)
    assert row.status == "SUBMITTED"
    assert row.trade_id == envelope.data.trade_id


async def test_double_approve_conflicts(service_session):
    pid = await _seed(service_session)
    await papi.approve_proposal(pid, BackgroundTasks(), service_session, FakeKis())
    with pytest.raises(HTTPException) as exc:
        # SUBMITTED 상태 → 재승인 불가
        await papi.approve_proposal(pid, BackgroundTasks(), service_session, FakeKis())
    assert exc.value.status_code == 409


async def test_blocked_by_kill_switch_marks_failed(service_session):
    pid = await _seed(service_session, account_type="REAL")
    safety.set_kill_switch(True, reason="halt")
    fake = FakeKis(fail=True)  # 게이트에서 막혀야 하므로 브로커 호출 금지
    response = await papi.approve_proposal(
        pid, BackgroundTasks(), service_session, fake
    )
    assert isinstance(response, JSONResponse)
    assert response.status_code == 403
    row = await service_session.get(OrderProposal, pid)
    assert row.status == "FAILED"
    assert "kill switch" in (row.reason_json or "")


async def test_idempotent_replay_after_crash(service_session):
    # 승인 후 제출 직전 크래시한 시나리오: APPROVED + 키 존재 + 트레이드 이미 기록.
    pid = await _seed(
        service_session, status="APPROVED", client_order_id="crashkey1"
    )
    service_session.add(
        Trade(
            account_type="PAPER",
            stock_code="005930",
            direction="SELL",
            quantity=3,
            price=Decimal("70000"),
            executed_at=datetime.now(),
            client_order_id="crashkey1",
        )
    )
    # trades.account_type FK 충족용 계좌 행
    from shared.db.models import Account

    service_session.add(
        Account(type="PAPER", app_key="x", app_secret="y", account_no="z")
    )
    await service_session.commit()

    fake = FakeKis(fail=True)  # 재시도에서 브로커 재호출은 금지
    envelope = await papi.approve_proposal(
        pid, BackgroundTasks(), service_session, fake
    )
    assert envelope.error is None
    assert "idempotent" in envelope.data.note
    row = await service_session.get(OrderProposal, pid)
    assert row.status == "SUBMITTED"


async def test_reject_transitions_once(service_session):
    pid = await _seed(service_session)
    envelope = await papi.reject_proposal(pid, service_session)
    assert envelope.data.status == "REJECTED"
    with pytest.raises(HTTPException) as exc:
        await papi.reject_proposal(pid, service_session)
    assert exc.value.status_code == 409


async def test_list_filters_by_status(service_session):
    await _seed(service_session, stock_code="000001")
    await _seed(service_session, stock_code="000002", status="EXPIRED")
    envelope = await papi.list_proposals("PROPOSED", None, service_session)
    codes = [p.stock_code for p in envelope.data]
    assert codes == ["000001"]
    assert envelope.data[0].reason == {"rule": "BAND_TRIM"}
