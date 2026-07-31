"""제안 승인·실행 서비스 — 앱(HTTP)과 텔레그램 트랙이 공유하는 단일 경로.

api/proposals.py의 승인 엔드포인트 본체를 그대로 옮긴 것: 원자적 CAS 클레임
→ 멱등 재생 → 주문요청 조립(KIS/Toss 분기) → 안전게이트(킬스위치·한도·
일일손실 + 연금계좌 차단) → 브로커 제출 → trade skeleton. HTTP 표현(상태
코드·봉투)은 호출자 몫이고, 이 모듈은 ApproveOutcome만 돌려준다.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.portfolio import (
    _find_trade_by_client_order_id,
    _persist_trade_skeleton,
)
from backend.app.schemas.portfolio import OrderRequest, OrderType
from backend.app.services.brokers.factory import broker_client
from backend.app.services.kis.rest_client import KISRestClient, KISRestError
from backend.app.services.orders.guard import (
    OrderBlocked,
    assert_daily_loss_ok,
    guard_order,
)
from shared.db.models import OrderProposal
from shared.domain.account import AccountType, BrokerType
from shared.domain.trade import TradeDirection


@dataclass(slots=True)
class ApproveOutcome:
    """승인 시도의 결과 — 호출자(HTTP/텔레그램)가 표현을 결정한다."""

    status: str  # not_found | conflict | blocked | failed | submitted | replayed
    proposal: OrderProposal | None = None
    trade_id: int | None = None
    note: str = ""
    error_code: str | None = None
    error_payload: dict | None = None
    http_status: int = 200
    should_track: bool = False


def order_request_for(
    proposal: OrderProposal, *, client_order_id: str
) -> OrderRequest:
    """제안 → 주문요청. market='US'는 Toss(계좌 개념·zfill 없음), 그 외 KIS."""
    if (proposal.market or "KR").upper() == "US":
        return OrderRequest(
            broker=BrokerType.TOSS,
            client_order_id=client_order_id,
            stock_code=proposal.stock_code,
            direction=TradeDirection(proposal.side),
            quantity=proposal.qty,
            order_type=OrderType.LIMIT,
            price=proposal.limit_price or Decimal("0"),
        )
    return OrderRequest(
        broker=BrokerType.KIS,
        account_type=AccountType(proposal.account_type),
        client_order_id=client_order_id,
        stock_code=proposal.stock_code.zfill(6),
        direction=TradeDirection(proposal.side),
        quantity=proposal.qty,
        order_type=OrderType.LIMIT,
        price=proposal.limit_price or Decimal("0"),
    )


async def mark_proposal(
    session: AsyncSession,
    proposal: OrderProposal,
    new_status: str,
    *,
    trade_id: int | None = None,
    note: str | None = None,
) -> None:
    values: dict[str, Any] = {"status": new_status, "updated_at": datetime.now()}
    if trade_id is not None:
        values["trade_id"] = trade_id
    if note:
        reason: dict[str, Any] = {}
        if proposal.reason_json:
            try:
                reason = json.loads(proposal.reason_json)
            except ValueError:
                reason = {"raw": proposal.reason_json}
        reason["error"] = note[:300]
        values["reason_json"] = json.dumps(reason, ensure_ascii=False)
    await session.execute(
        update(OrderProposal).where(OrderProposal.id == proposal.id).values(**values)
    )
    await session.commit()
    await session.refresh(proposal)


async def reject_proposal_cas(
    proposal_id: int, *, session: AsyncSession
) -> OrderProposal | None:
    """PROPOSED → REJECTED 원자 전이. 이미 처리됐으면 None."""
    result = await session.execute(
        update(OrderProposal)
        .where(OrderProposal.id == proposal_id)
        .where(OrderProposal.status == "PROPOSED")
        .values(status="REJECTED", updated_at=datetime.now())
    )
    await session.commit()
    if (result.rowcount or 0) != 1:
        return None
    return await session.get(OrderProposal, proposal_id)


async def approve_and_execute(
    proposal_id: int,
    *,
    session: AsyncSession,
    kis_client: KISRestClient,
) -> ApproveOutcome:
    """승인 → 안전게이트 → 브로커 제출 (api/proposals.py 승인 본체 이동).

    - 원자적 클레임: PROPOSED에서만 APPROVED로 전이(연타 시 conflict)
    - 크래시 복구: APPROVED+client_order_id는 같은 키로 멱등 재시도
    - 차단(킬스위치/한도/일일손실/연금 TR): FAILED 마킹 + blocked
    """
    proposal = await session.get(OrderProposal, proposal_id)
    if proposal is None:
        return ApproveOutcome(status="not_found", note="Proposal not found.")

    if proposal.status == "PROPOSED":
        client_order_id = uuid.uuid4().hex
        claimed = await session.execute(
            update(OrderProposal)
            .where(OrderProposal.id == proposal_id)
            .where(OrderProposal.status == "PROPOSED")
            .values(
                status="APPROVED",
                approved_at=datetime.now(),
                client_order_id=client_order_id,
                updated_at=datetime.now(),
            )
        )
        await session.commit()
        if (claimed.rowcount or 0) != 1:
            return ApproveOutcome(
                status="conflict", note="Proposal already handled."
            )
        await session.refresh(proposal)
    elif proposal.status == "APPROVED" and proposal.client_order_id:
        # 제출 도중 크래시했던 승인 건 — 같은 키로 멱등 재시도.
        pass
    else:
        return ApproveOutcome(
            status="conflict",
            note=f"Proposal is {proposal.status}, not approvable.",
        )

    existing = await _find_trade_by_client_order_id(
        session, proposal.client_order_id
    )
    if existing is not None:
        await mark_proposal(session, proposal, "SUBMITTED", trade_id=existing.id)
        return ApproveOutcome(
            status="replayed",
            proposal=proposal,
            trade_id=existing.id,
            note="idempotent replay — order already submitted",
        )

    request = order_request_for(
        proposal, client_order_id=proposal.client_order_id
    )

    try:
        guard_order(request, reference_price=proposal.last_price)
        await assert_daily_loss_ok(
            session,
            broker=request.broker,
            account_type=request.account_type,
            direction=request.direction,
        )
    except OrderBlocked as exc:
        await mark_proposal(session, proposal, "FAILED", note=str(exc))
        return ApproveOutcome(status="blocked", proposal=proposal, note=str(exc))

    try:
        if request.broker is BrokerType.TOSS:
            # Toss 실행 — toss_is_mock=true면 클라이언트가 모의 응답을 돌려준다
            # (실체결 없음). 실주문 전환은 라이브 잠금 해제 + 소액 스모크 후.
            order = await broker_client(BrokerType.TOSS).place_order(request)
        else:
            order = await kis_client.place_order(request)
    except KISRestError as exc:
        await mark_proposal(session, proposal, "FAILED", note=str(exc))
        return ApproveOutcome(
            status="failed",
            proposal=proposal,
            note=str(exc),
            error_code="KIS_ORDER_FAILED",
            error_payload=exc.payload,
            http_status=(
                exc.status_code
                if exc.status_code and exc.status_code >= 400
                else 502
            ),
        )
    except Exception as exc:  # noqa: BLE001 — Toss 오류: 재시도 금지, 실패 마킹
        await mark_proposal(session, proposal, "FAILED", note=str(exc))
        return ApproveOutcome(
            status="failed",
            proposal=proposal,
            note=str(exc),
            error_code="TOSS_ORDER_FAILED",
            http_status=502,
        )

    persistence = await _persist_trade_skeleton(session, order, request)
    await mark_proposal(
        session, proposal, "SUBMITTED", trade_id=persistence.trade_id
    )
    return ApproveOutcome(
        status="submitted",
        proposal=proposal,
        trade_id=persistence.trade_id,
        note=persistence.note,
        should_track=bool(
            persistence.persisted and persistence.trade_id and order.kis_order_no
        ),
    )
