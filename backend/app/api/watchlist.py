"""Watchlist category and entry CRUD API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.schemas.portfolio import ApiEnvelope
from shared.db.models import WatchlistCategory, WatchlistEntry
from shared.db.session import get_service_session

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchlistCategoryCreate(BaseModel):
    name: str = Field(min_length=1)
    color: str = "#888888"
    sort_order: int = 0

    @field_validator("name", "color")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class WatchlistCategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    color: str | None = None
    sort_order: int | None = None

    @field_validator("name", "color")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class WatchlistCategoryResponse(BaseModel):
    id: int
    name: str
    color: str
    sort_order: int


class WatchlistEntryCreate(BaseModel):
    stock_code: str = Field(min_length=1, max_length=20)
    category_id: int
    reason: str = Field(min_length=1)

    @field_validator("stock_code")
    @classmethod
    def normalize_stock_code(cls, value: str) -> str:
        return _normalize_watchlist_symbol(value)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason must not be blank")
        return stripped


class WatchlistEntryPatch(BaseModel):
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason must not be blank")
        return stripped


class WatchlistEntryResponse(BaseModel):
    id: int
    stock_code: str
    symbol: str
    market_country: str
    broker: str
    category_id: int
    reason: str
    added_at: datetime


@router.get("/categories", response_model=ApiEnvelope[list[WatchlistCategoryResponse]])
async def list_categories(
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[list[WatchlistCategoryResponse]]:
    result = await session.execute(
        select(WatchlistCategory).order_by(
            WatchlistCategory.sort_order,
            WatchlistCategory.id,
        )
    )
    categories = [_category_response(category) for category in result.scalars()]
    return ApiEnvelope(data=categories, error=None)


@router.post(
    "/categories",
    response_model=ApiEnvelope[WatchlistCategoryResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    payload: WatchlistCategoryCreate,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[WatchlistCategoryResponse]:
    category = WatchlistCategory(
        name=payload.name,
        color=payload.color,
        sort_order=payload.sort_order,
    )
    session.add(category)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Category name already exists") from exc
    await session.refresh(category)
    return ApiEnvelope(data=_category_response(category), error=None)


@router.patch(
    "/categories/{category_id}",
    response_model=ApiEnvelope[WatchlistCategoryResponse],
)
async def patch_category(
    category_id: int,
    payload: WatchlistCategoryPatch,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[WatchlistCategoryResponse]:
    category = await session.get(WatchlistCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(category, field, value)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Category name already exists") from exc
    await session.refresh(category)
    return ApiEnvelope(data=_category_response(category), error=None)


@router.delete("/categories/{category_id}", response_model=ApiEnvelope[dict[str, Any]])
async def delete_category(
    category_id: int,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[dict[str, Any]]:
    category = await session.get(WatchlistCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    await session.delete(category)
    await session.commit()
    return ApiEnvelope(data={"deleted": True, "id": category_id}, error=None)


@router.get("/entries", response_model=ApiEnvelope[list[WatchlistEntryResponse]])
async def list_entries(
    category_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[list[WatchlistEntryResponse]]:
    stmt = select(WatchlistEntry)
    if category_id is not None:
        stmt = stmt.where(WatchlistEntry.category_id == category_id)
    stmt = stmt.order_by(WatchlistEntry.added_at.desc(), WatchlistEntry.id.desc())
    result = await session.execute(stmt)
    entries = [_entry_response(entry) for entry in result.scalars()]
    return ApiEnvelope(data=entries, error=None)


@router.post(
    "/entries",
    response_model=ApiEnvelope[WatchlistEntryResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_entry(
    payload: WatchlistEntryCreate,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[WatchlistEntryResponse]:
    category = await session.get(WatchlistCategory, payload.category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    entry = WatchlistEntry(
        stock_code=payload.stock_code,
        category_id=payload.category_id,
        reason=payload.reason,
    )
    session.add(entry)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Stock already exists in this category",
        ) from exc
    await session.refresh(entry)
    return ApiEnvelope(data=_entry_response(entry), error=None)


@router.patch("/entries/{entry_id}", response_model=ApiEnvelope[WatchlistEntryResponse])
async def patch_entry(
    entry_id: int,
    payload: WatchlistEntryPatch,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[WatchlistEntryResponse]:
    entry = await session.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    entry.reason = payload.reason
    await session.commit()
    await session.refresh(entry)
    return ApiEnvelope(data=_entry_response(entry), error=None)


@router.delete("/entries/{entry_id}", response_model=ApiEnvelope[dict[str, Any]])
async def delete_entry(
    entry_id: int,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[dict[str, Any]]:
    entry = await session.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    await session.delete(entry)
    await session.commit()
    return ApiEnvelope(data={"deleted": True, "id": entry_id}, error=None)


def _category_response(category: WatchlistCategory) -> WatchlistCategoryResponse:
    return WatchlistCategoryResponse(
        id=category.id,
        name=category.name,
        color=category.color,
        sort_order=category.sort_order,
    )


def _entry_response(entry: WatchlistEntry) -> WatchlistEntryResponse:
    symbol = _normalize_watchlist_symbol(entry.stock_code)
    market_country = "KR" if symbol.isdigit() else "US"
    return WatchlistEntryResponse(
        id=entry.id,
        stock_code=symbol,
        symbol=symbol,
        market_country=market_country,
        broker="KIS" if market_country == "KR" else "TOSS",
        category_id=entry.category_id,
        reason=entry.reason,
        added_at=entry.added_at,
    )


def _normalize_watchlist_symbol(value: str) -> str:
    stripped = value.strip().upper()
    return stripped.zfill(6) if stripped.isdigit() else stripped
