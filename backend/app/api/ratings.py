"""등급(레이팅) 조회/온디맨드 재계산 API (Phase T5).

``/``, ``/positions``, ``/status`` 는 배치(``rating_batch.py``)가 이미 채워둔
``store.py`` 결과를 읽기만 한다. ``/compute`` 는 온디맨드 1종목 재계산 —
배치와 동일하게 ``store.RATING_LOCK``을 잡아 동시 upsert 경합을 막는다
(이미 잠겨 있으면 계산을 시도하지 않고 409로 응답한다).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.schemas.portfolio import ApiEnvelope, ApiError
from backend.app.services.ratings import store
from backend.app.services.ratings.buy_axis import (
    compute_buy_ratings,
    resolve_rating_strategy,
)
from research.factors.common import normalize_code
from shared.db.models import Setting
from shared.db.session import get_service_session

router = APIRouter(prefix="/api/ratings", tags=["ratings"])


@router.get("", response_model=ApiEnvelope[list[dict[str, Any]]])
async def get_ratings(
    codes: str = Query(default=""),
) -> ApiEnvelope[list[dict[str, Any]]]:
    parsed = [normalize_code(raw) for raw in codes.split(",") if raw.strip()]
    if not parsed:
        return ApiEnvelope(data=[], error=None)
    rows = await store.get_stock_ratings(parsed)
    return ApiEnvelope(data=rows, error=None)


@router.get("/positions", response_model=ApiEnvelope[list[dict[str, Any]]])
async def get_positions_ratings() -> ApiEnvelope[list[dict[str, Any]]]:
    rows = await store.get_position_ratings()
    return ApiEnvelope(data=rows, error=None)


@router.post("/compute", response_model=ApiEnvelope[dict[str, Any]])
async def compute_rating(
    code: str = Query(...),
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[dict[str, Any]]:
    normalized = normalize_code(code)
    if not normalized.isdigit():
        # US 티커 등 매수축 스코어링 유니버스 밖의 종목 — 채점 없이 즉시 응답.
        return ApiEnvelope(data=_rating_dict(normalized, "UNSUPPORTED"), error=None)

    if store.RATING_LOCK.locked():
        envelope = ApiEnvelope(
            data=None,
            error=ApiError(
                code="RATING_BUSY",
                message="등급 계산이 진행 중입니다",
                details=None,
            ),
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=envelope.model_dump(mode="json"),
        )

    async with store.RATING_LOCK:
        setting_row = await session.get(Setting, "rating_strategy_name")
        strategy, _warning = resolve_rating_strategy(
            setting_row.value if setting_row is not None else None
        )
        result = await asyncio.to_thread(
            compute_buy_ratings, strategy, [normalized], as_of=None
        )
        await store.upsert_stock_ratings(
            result.ratings, result.strategy_name, result.as_of
        )

    # 저장된 행을 그대로 반환해 GET /api/ratings 와 동일한 스키마
    # (strategy_name/as_of/updated_at 포함)를 보장한다 — 단일 진실원.
    stored = await store.get_stock_ratings([normalized])
    if stored:
        return ApiEnvelope(data=stored[0], error=None)
    return ApiEnvelope(data=_rating_dict(normalized, "NO_DATA"), error=None)


@router.get("/status", response_model=ApiEnvelope[dict[str, Any]])
async def get_ratings_status(
    request: Request,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[dict[str, Any]]:
    runs = await store.latest_runs()
    setting_row = await session.get(Setting, "rating_strategy_name")
    strategy_name = (
        setting_row.value if setting_row is not None else settings.DEFAULT_STRATEGY_NAME
    )
    data = {
        "eod": runs.get("EOD"),
        "intraday": runs.get("INTRADAY") or runs.get("EOD"),
        "strategy_name": strategy_name,
        "scheduler_running": hasattr(request.app.state, "batch_scheduler"),
    }
    return ApiEnvelope(data=data, error=None)


def _rating_dict(code: str, status_value: str) -> dict[str, Any]:
    return {
        "code": code,
        "status": status_value,
        "buy_grade": None,
        "score": None,
        "percentile": None,
        "weakest_group": None,
    }
