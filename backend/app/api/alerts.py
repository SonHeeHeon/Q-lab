"""Alert history and CRUD API."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.market_data.names import lookup_stock_names
from shared.db.models import Alert
from shared.db.session import get_service_session

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

AlertConditionWire = Literal[
    "PRICE_ABOVE",
    "PRICE_BELOW",
    "PCT_CHANGE",
    "VOLUME_SPIKE",
]


class AlertCreate(BaseModel):
    stock_code: str = Field(min_length=1, max_length=12)
    condition: AlertConditionWire
    threshold: float

    @field_validator("stock_code")
    @classmethod
    def normalize_stock_code(cls, value: str) -> str:
        return value.strip().zfill(6)


class AlertPostMortemPatch(BaseModel):
    post_mortem: str = Field(min_length=1)

    @field_validator("post_mortem")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("post_mortem must not be blank")
        return stripped


class AlertResponse(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    condition: str
    threshold: float
    status: Literal["pending", "triggered", "cancelled"]
    created_at: datetime
    triggered_at: datetime | None
    post_mortem: str | None


@router.get("", response_model=ApiEnvelope[list[AlertResponse]])
async def list_alerts(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[list[AlertResponse]]:
    stmt = select(Alert)
    if from_ is not None:
        stmt = stmt.where(Alert.created_at >= from_)
    if to is not None:
        stmt = stmt.where(Alert.created_at <= to)
    stmt = stmt.order_by(Alert.created_at.desc(), Alert.id.desc())
    result = await session.execute(stmt)
    alerts = list(result.scalars())
    return ApiEnvelope(data=await _alert_responses(alerts), error=None)


@router.post(
    "",
    response_model=ApiEnvelope[AlertResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_alert(
    payload: AlertCreate,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[AlertResponse]:
    alert = Alert(
        stock_code=payload.stock_code,
        condition=payload.condition,
        threshold=payload.threshold,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return ApiEnvelope(data=(await _alert_responses([alert]))[0], error=None)


@router.delete("/{alert_id}", response_model=ApiEnvelope[dict[str, Any]])
async def delete_alert(
    alert_id: int,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[dict[str, Any]]:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    await session.delete(alert)
    await session.commit()
    return ApiEnvelope(data={"deleted": True, "id": alert_id}, error=None)


@router.patch(
    "/{alert_id}/post-mortem",
    response_model=ApiEnvelope[AlertResponse],
)
async def patch_alert_post_mortem(
    alert_id: int,
    payload: AlertPostMortemPatch,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[AlertResponse]:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.post_mortem = payload.post_mortem
    await session.commit()
    await session.refresh(alert)
    return ApiEnvelope(data=(await _alert_responses([alert]))[0], error=None)


async def _alert_responses(alerts: list[Alert]) -> list[AlertResponse]:
    names = await asyncio.to_thread(
        lookup_stock_names,
        [alert.stock_code for alert in alerts],
    )
    return [
        AlertResponse(
            id=alert.id,
            stock_code=alert.stock_code,
            stock_name=names.get(alert.stock_code) or alert.stock_code,
            condition=_to_flutter_condition(alert.condition),
            threshold=alert.threshold,
            status="triggered" if alert.triggered_at is not None else "pending",
            created_at=alert.created_at,
            triggered_at=alert.triggered_at,
            post_mortem=alert.post_mortem,
        )
        for alert in alerts
    ]


def _to_flutter_condition(condition: str) -> str:
    mapping = {
        "PRICE_GTE": "PRICE_ABOVE",
        "PRICE_LTE": "PRICE_BELOW",
        "PCT_DROP": "PCT_CHANGE",
        "PCT_RISE": "PCT_CHANGE",
    }
    return mapping.get(condition.upper(), condition.upper())
