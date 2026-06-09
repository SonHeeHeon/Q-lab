"""Trade journal API."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.llm.journal_analyzer import analyze_trade_journal_entry
from shared.db.models import Principle, Trade, TradeJournalEntry
from shared.db.session import get_service_session

router = APIRouter(prefix="/api/trade-journal", tags=["trade-journal"])


class PrincipleLiteResponse(BaseModel):
    id: int
    title: str
    category: str


class TradeLiteResponse(BaseModel):
    id: int
    account_type: str
    stock_code: str
    direction: str
    quantity: int
    price: float
    executed_at: datetime
    kis_order_no: str | None = None
    status: str = "PENDING"
    filled_quantity: int = 0
    filled_price: float | None = None
    fees: float = 0
    taxes: float = 0
    filled_at: datetime | None = None


class TradeJournalCreate(BaseModel):
    trade_id: int
    reason: str = Field(min_length=1)
    applied_principle_ids: list[int] = Field(default_factory=list)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason must not be blank")
        return stripped


class TradeJournalPatch(BaseModel):
    reason: str | None = Field(default=None, min_length=1)
    post_review: str | None = None
    applied_principle_ids: list[int] | None = None

    @field_validator("reason", "post_review")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class TradeJournalResponse(BaseModel):
    id: int
    trade_id: int
    direction: str
    reason: str
    post_review: str | None
    llm_analysis_summary: str | None = None
    llm_violation_tags: list[str] = Field(default_factory=list)
    llm_analyzed_at: datetime | None = None
    llm_analysis_model: str | None = None
    created_at: datetime
    trade: TradeLiteResponse
    applied_principles: list[PrincipleLiteResponse]


@router.get("", response_model=ApiEnvelope[list[TradeJournalResponse]])
async def list_trade_journal(
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[list[TradeJournalResponse]]:
    stmt = (
        select(TradeJournalEntry)
        .options(
            selectinload(TradeJournalEntry.trade),
            selectinload(TradeJournalEntry.applied_principles),
        )
        .order_by(TradeJournalEntry.created_at.desc(), TradeJournalEntry.id.desc())
    )
    result = await session.execute(stmt)
    entries = [_journal_response(entry) for entry in result.scalars()]
    return ApiEnvelope(data=entries, error=None)


@router.post(
    "",
    response_model=ApiEnvelope[TradeJournalResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_trade_journal_entry(
    payload: TradeJournalCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[TradeJournalResponse]:
    trade = await session.get(Trade, payload.trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    principles = await _load_principles(session, payload.applied_principle_ids)
    entry = TradeJournalEntry(
        trade_id=trade.id,
        direction=trade.direction,
        reason=payload.reason,
        applied_principles=principles,
    )
    session.add(entry)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Journal entry already exists for this trade",
        ) from exc

    stmt = (
        select(TradeJournalEntry)
        .where(TradeJournalEntry.id == entry.id)
        .options(
            selectinload(TradeJournalEntry.trade),
            selectinload(TradeJournalEntry.applied_principles),
        )
    )
    result = await session.execute(stmt)
    created = result.scalar_one()
    background_tasks.add_task(analyze_trade_journal_entry, created.id)
    return ApiEnvelope(data=_journal_response(created), error=None)


@router.patch("/{journal_id}", response_model=ApiEnvelope[TradeJournalResponse])
async def patch_trade_journal_entry(
    journal_id: int,
    payload: TradeJournalPatch,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[TradeJournalResponse]:
    stmt = (
        select(TradeJournalEntry)
        .where(TradeJournalEntry.id == journal_id)
        .options(
            selectinload(TradeJournalEntry.trade),
            selectinload(TradeJournalEntry.applied_principles),
        )
    )
    result = await session.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    updates = payload.model_dump(exclude_unset=True)
    if "reason" in updates and updates["reason"] is not None:
        entry.reason = updates["reason"]
    if "post_review" in updates:
        entry.post_review = updates["post_review"]
    if "applied_principle_ids" in updates and updates["applied_principle_ids"] is not None:
        entry.applied_principles = await _load_principles(
            session,
            updates["applied_principle_ids"],
        )

    await session.commit()
    result = await session.execute(stmt)
    updated = result.scalar_one()
    background_tasks.add_task(analyze_trade_journal_entry, updated.id)
    return ApiEnvelope(data=_journal_response(updated), error=None)


@router.get("/missing", response_model=ApiEnvelope[list[TradeLiteResponse]])
async def list_missing_journal_trades(
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[list[TradeLiteResponse]]:
    stmt = (
        select(Trade)
        .outerjoin(TradeJournalEntry, TradeJournalEntry.trade_id == Trade.id)
        .where(TradeJournalEntry.id.is_(None))
        .order_by(Trade.executed_at.desc(), Trade.id.desc())
    )
    result = await session.execute(stmt)
    trades = [_trade_response(trade) for trade in result.scalars()]
    return ApiEnvelope(data=trades, error=None)


async def _load_principles(
    session: AsyncSession,
    principle_ids: list[int],
) -> list[Principle]:
    unique_ids = sorted(set(principle_ids))
    if not unique_ids:
        return []

    result = await session.execute(
        select(Principle).where(Principle.id.in_(unique_ids))
    )
    principles = list(result.scalars())
    found_ids = {principle.id for principle in principles}
    missing = [principle_id for principle_id in unique_ids if principle_id not in found_ids]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Principle ids not found: {missing}",
        )
    return principles


def _journal_response(entry: TradeJournalEntry) -> TradeJournalResponse:
    return TradeJournalResponse(
        id=entry.id,
        trade_id=entry.trade_id,
        direction=entry.direction,
        reason=entry.reason,
        post_review=entry.post_review,
        llm_analysis_summary=entry.llm_analysis_summary,
        llm_violation_tags=_decode_violation_tags(entry.llm_violation_tags),
        llm_analyzed_at=entry.llm_analyzed_at,
        llm_analysis_model=entry.llm_analysis_model,
        created_at=entry.created_at,
        trade=_trade_response(entry.trade),
        applied_principles=[
            PrincipleLiteResponse(
                id=principle.id,
                title=principle.title,
                category=principle.category,
            )
            for principle in entry.applied_principles
        ],
    )


def _trade_response(trade: Trade) -> TradeLiteResponse:
    return TradeLiteResponse(
        id=trade.id,
        account_type=trade.account_type,
        stock_code=trade.stock_code,
        direction=trade.direction,
        quantity=trade.quantity,
        price=float(trade.price),
        executed_at=trade.executed_at,
        kis_order_no=trade.kis_order_no,
        status=trade.status,
        filled_quantity=trade.filled_quantity,
        filled_price=float(trade.filled_price) if trade.filled_price is not None else None,
        fees=float(trade.fees),
        taxes=float(trade.taxes),
        filled_at=trade.filled_at,
    )


def _decode_violation_tags(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []
    try:
        value = json.loads(raw_tags)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
