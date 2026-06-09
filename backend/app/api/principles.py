"""Investment principle CRUD API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.schemas.portfolio import ApiEnvelope
from shared.db.models import Principle
from shared.db.session import get_service_session
from shared.domain.principle import PrincipleCategory

router = APIRouter(prefix="/api/principles", tags=["principles"])


class PrincipleCreate(BaseModel):
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    category: PrincipleCategory

    @field_validator("title", "body")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class PrinciplePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    body: str | None = Field(default=None, min_length=1)
    category: PrincipleCategory | None = None

    @field_validator("title", "body")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class PrincipleResponse(BaseModel):
    id: int
    title: str
    body: str
    category: PrincipleCategory
    is_editable: bool
    updated_at: datetime


@router.get("", response_model=ApiEnvelope[list[PrincipleResponse]])
async def list_principles(
    category: PrincipleCategory | None = Query(default=None),
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[list[PrincipleResponse]]:
    stmt = select(Principle)
    if category is not None:
        stmt = stmt.where(Principle.category == category.value)
    stmt = stmt.order_by(Principle.category, Principle.id)
    result = await session.execute(stmt)
    principles = [_principle_response(principle) for principle in result.scalars()]
    return ApiEnvelope(data=principles, error=None)


@router.post(
    "",
    response_model=ApiEnvelope[PrincipleResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_principle(
    payload: PrincipleCreate,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[PrincipleResponse]:
    principle = Principle(
        title=payload.title,
        body=payload.body,
        category=payload.category.value,
        is_editable=True,
        updated_at=datetime.now(),
    )
    session.add(principle)
    await session.commit()
    await session.refresh(principle)
    return ApiEnvelope(data=_principle_response(principle), error=None)


@router.patch("/{principle_id}", response_model=ApiEnvelope[PrincipleResponse])
async def patch_principle(
    principle_id: int,
    payload: PrinciplePatch,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[PrincipleResponse]:
    principle = await session.get(Principle, principle_id)
    if principle is None:
        raise HTTPException(status_code=404, detail="Principle not found")
    if not principle.is_editable:
        raise HTTPException(status_code=403, detail="Principle is not editable")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(principle, field, value.value if isinstance(value, PrincipleCategory) else value)
    principle.updated_at = datetime.now()

    await session.commit()
    await session.refresh(principle)
    return ApiEnvelope(data=_principle_response(principle), error=None)


@router.delete("/{principle_id}", response_model=ApiEnvelope[dict[str, Any]])
async def delete_principle(
    principle_id: int,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[dict[str, Any]]:
    principle = await session.get(Principle, principle_id)
    if principle is None:
        raise HTTPException(status_code=404, detail="Principle not found")
    if not principle.is_editable:
        raise HTTPException(status_code=403, detail="Principle is not editable")

    await session.delete(principle)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Principle is referenced by a trade journal entry",
        ) from exc
    return ApiEnvelope(data={"deleted": True, "id": principle_id}, error=None)


def _principle_response(principle: Principle) -> PrincipleResponse:
    return PrincipleResponse(
        id=principle.id,
        title=principle.title,
        body=principle.body,
        category=PrincipleCategory(principle.category),
        is_editable=principle.is_editable,
        updated_at=principle.updated_at,
    )
