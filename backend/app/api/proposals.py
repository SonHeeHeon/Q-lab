"""승인형 반자동 — 주문 제안 조회/승인/거절 API.

승인은 원자적 상태 전이(PROPOSED→APPROVED, 조건부 UPDATE)로 클레임한 뒤
수동 주문과 **동일한 안전 경로**(guard_order + 일일손실 한도 + client_order_id
멱등)를 거쳐 브로커로 나간다. 승인 버튼 연타·재시도에도 주문은 1건이다.
"""

from __future__ import annotations

import json
from datetime import date as Date
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.portfolio import (
    _schedule_order_tracking,
    get_kis_rest_client,
)
from backend.app.schemas.portfolio import ApiEnvelope, ApiError
from backend.app.services.batch.proposal_generator import (
    run_proposal_generation,
    run_sleeve_proposals,
)
from backend.app.services.batch.us_advisory import generate_us_advisory
from backend.app.services.kis.rest_client import KISRestClient
from backend.app.services.orders.approval import (
    approve_and_execute,
    order_request_for as _order_request_for,  # 기존 테스트 호환 별칭
)
from shared.db.models import OrderProposal
from shared.db.session import get_service_session

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


class ProposalResponse(BaseModel):
    id: int
    batch_id: str
    proposal_date: Date
    account_type: str
    strategy_name: str
    stock_code: str
    market: str
    side: str
    qty: int
    order_type: str
    limit_price: float | None
    last_price: float | None
    estimated_notional: float | None
    reason: dict[str, Any]
    status: str
    expires_at: datetime | None
    approved_at: datetime | None
    trade_id: int | None
    created_at: datetime


class ApproveResult(BaseModel):
    proposal: ProposalResponse
    trade_id: int | None
    note: str


class GenerateRequest(BaseModel):
    strategy_name: str | None = None
    full_rebalance: bool = False
    send_telegram: bool = False


def _to_response(row: OrderProposal) -> ProposalResponse:
    reason: dict[str, Any] = {}
    if row.reason_json:
        try:
            reason = json.loads(row.reason_json)
        except ValueError:
            reason = {"raw": row.reason_json}
    return ProposalResponse(
        id=row.id,
        batch_id=row.batch_id,
        proposal_date=row.proposal_date,
        account_type=row.account_type,
        strategy_name=row.strategy_name,
        stock_code=row.stock_code,
        market=row.market,
        side=row.side,
        qty=row.qty,
        order_type=row.order_type,
        limit_price=float(row.limit_price) if row.limit_price is not None else None,
        last_price=float(row.last_price) if row.last_price is not None else None,
        estimated_notional=(
            float(row.estimated_notional)
            if row.estimated_notional is not None
            else None
        ),
        reason=reason,
        status=row.status,
        expires_at=row.expires_at,
        approved_at=row.approved_at,
        trade_id=row.trade_id,
        created_at=row.created_at,
    )


@router.get("", response_model=ApiEnvelope[list[ProposalResponse]])
async def list_proposals(
    status_filter: str | None = Query(default=None, alias="status"),
    proposal_date: Date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[list[ProposalResponse]]:
    stmt = select(OrderProposal).order_by(
        OrderProposal.created_at.desc(), OrderProposal.id.desc()
    )
    if status_filter:
        stmt = stmt.where(OrderProposal.status == status_filter.upper())
    if proposal_date:
        stmt = stmt.where(OrderProposal.proposal_date == proposal_date)
    rows = list((await session.execute(stmt.limit(200))).scalars())
    return ApiEnvelope(data=[_to_response(row) for row in rows], error=None)


@router.post("/generate", response_model=ApiEnvelope[dict[str, Any]])
async def generate_proposals(
    payload: GenerateRequest,
) -> ApiEnvelope[dict[str, Any]]:
    """수동 트리거 — 배치와 동일한 생성 로직 실행.

    strategy_name이 없으면 2-슬리브 오케스트레이터(run_sleeve_proposals)를,
    명시되면 (내부적으로 슬리브 스코핑이 적용된) 단일 run_proposal_generation을
    실행한다.
    """
    if payload.strategy_name is None:
        summary = await run_sleeve_proposals(send_telegram=payload.send_telegram)
    else:
        summary = await run_proposal_generation(
            strategy_name=payload.strategy_name,
            full_rebalance=payload.full_rebalance,
            send_telegram=payload.send_telegram,
        )
    return ApiEnvelope(data=summary, error=None)


@router.get("/us-advisory", response_model=ApiEnvelope[dict[str, Any]])
async def us_advisory(
    strategy: str = Query(default="us_stock_v1"),
    top_n: int | None = Query(default=None),
) -> ApiEnvelope[dict[str, Any]]:
    """US 자문 슬리브(실주문 없음) — US 퀀트 방정식으로 US_LARGE를 랭킹해
    Toss 보유 대비 BUY/SELL/HOLD 자문을 반환한다. OrderProposal을 만들지 않아
    승인/실행 파이프라인과 완전히 분리된다."""
    try:
        result = await generate_us_advisory(strategy, top_n=top_n)
    except FileNotFoundError:
        # 튜닝판(us_value 등)은 private/ 전용 — 오픈소스 클론에는 없다.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"전략 파일 없음: {strategy} (튜닝판은 private/ 전용, "
            f"공개 기본은 us_stock_v1)",
        )
    return ApiEnvelope(data=result, error=None)


@router.post("/{proposal_id}/reject", response_model=ApiEnvelope[ProposalResponse])
async def reject_proposal(
    proposal_id: int,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[ProposalResponse]:
    result = await session.execute(
        update(OrderProposal)
        .where(OrderProposal.id == proposal_id)
        .where(OrderProposal.status == "PROPOSED")
        .values(status="REJECTED", updated_at=datetime.now())
    )
    await session.commit()
    if (result.rowcount or 0) != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal is not in PROPOSED state.",
        )
    row = await session.get(OrderProposal, proposal_id)
    return ApiEnvelope(data=_to_response(row), error=None)


@router.post("/{proposal_id}/approve", response_model=ApiEnvelope[ApproveResult])
async def approve_proposal(
    proposal_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_service_session),
    kis_client: KISRestClient = Depends(get_kis_rest_client),
) -> ApiEnvelope[ApproveResult]:
    """제안 승인 → 안전 게이트 통과 시 브로커 제출.

    - 원자적 클레임: PROPOSED에서만 APPROVED로 전이(연타 시 두 번째는 409)
    - 크래시 복구: 이미 APPROVED인 제안은 같은 client_order_id로 멱등 재시도
    - 차단(킬스위치/한도/일일손실): status=FAILED + 403 — 재생성으로만 부활

    본체는 services.orders.approval.approve_and_execute — 텔레그램 승인
    트랙과 공유. 이 함수는 Outcome→HTTP 표현 매핑만 담당한다.
    """
    outcome = await approve_and_execute(
        proposal_id, session=session, kis_client=kis_client
    )
    if outcome.status == "not_found":
        raise HTTPException(status_code=404, detail=outcome.note)
    if outcome.status == "conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=outcome.note
        )
    if outcome.status == "blocked":
        return _blocked_envelope(outcome.note)
    if outcome.status == "failed":
        envelope = ApiEnvelope(
            data=None,
            error=ApiError(
                code=outcome.error_code or "ORDER_FAILED",
                message=outcome.note,
                details=outcome.error_payload,
            ),
        )
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=outcome.http_status,
            content=envelope.model_dump(mode="json"),
        )

    if outcome.should_track:
        background_tasks.add_task(_schedule_order_tracking, outcome.trade_id)
    return ApiEnvelope(
        data=ApproveResult(
            proposal=_to_response(outcome.proposal),
            trade_id=outcome.trade_id,
            note=outcome.note,
        ),
        error=None,
    )


@router.post(
    "/batches/{batch_id}/approve-all",
    response_model=ApiEnvelope[dict[str, Any]],
)
async def approve_batch(
    batch_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_service_session),
    kis_client: KISRestClient = Depends(get_kis_rest_client),
) -> ApiEnvelope[dict[str, Any]]:
    """배치 일괄 승인 — 건별로 동일한 안전 체크를 개별 수행."""
    rows = list(
        (
            await session.execute(
                select(OrderProposal.id)
                .where(OrderProposal.batch_id == batch_id)
                .where(OrderProposal.status == "PROPOSED")
                .order_by(OrderProposal.side.desc())  # SELL 먼저 (현금 확보)
            )
        ).scalars()
    )
    outcomes: dict[str, int] = {"submitted": 0, "blocked": 0, "failed": 0}
    for proposal_id in rows:
        try:
            envelope = await approve_proposal(
                proposal_id, background_tasks, session, kis_client
            )
            if isinstance(envelope, ApiEnvelope) and envelope.data is not None:
                outcomes["submitted"] += 1
            else:
                outcomes["blocked"] += 1
        except HTTPException:
            outcomes["failed"] += 1
        except Exception:
            outcomes["failed"] += 1
    return ApiEnvelope(
        data={"batch_id": batch_id, "total": len(rows), **outcomes}, error=None
    )


def _blocked_envelope(message: str):
    from fastapi.responses import JSONResponse

    envelope = ApiEnvelope(
        data=None,
        error=ApiError(code="ORDER_BLOCKED", message=message, details=None),
    )
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content=envelope.model_dump(mode="json"),
    )
