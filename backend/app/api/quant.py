"""Quant & AI REST API."""

from __future__ import annotations

from datetime import date as Date

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.schemas.portfolio import ApiEnvelope
from shared.db.models import BatchAnalysisResult, Stock
from shared.db.session import get_research_session, get_service_session

router = APIRouter(prefix="/api/quant", tags=["quant"])


class UndervaluedStockResponse(BaseModel):
    rank: int
    stock_code: str
    name: str | None = None
    market: str | None = None
    sector: str | None = None
    score: float
    llm_commentary: str | None = None


class UndervaluedResponse(BaseModel):
    analysis_date: Date | None
    strategy_name: str
    items: list[UndervaluedStockResponse]
    # LLM 코멘터리 상태: ready(존재) / generating(조회 트리거로 생성 중) /
    # off(scheduled 모드·대상 아님·데이터 없음). 하위호환 위해 Optional.
    commentary_status: str | None = None


# 조회 트리거 중복 방지 — (날짜:전략) 키. 단일 프로세스 가정, 재시작 시
# 자연 초기화(날짜 키 저장이 최종 방어).
_commentary_inflight: set[str] = set()


def _commentary_status_and_maybe_schedule(
    *,
    mode: str,
    selected_strategy: str,
    default_strategy: str,
    selected_date: Date | None,
    has_commentary: bool,
    has_rows: bool,
    schedule,
) -> str:
    """상태 판정 + on_view면 1회 생성 태스크 예약 (순수 분기 — 테스트 대상).

    생성 대상은 기본 전략 조회일 때만 — 크론(daily_report)과 동일 범위 유지
    (4슬리브 각각 LLM을 돌리는 확장은 비용 목적에 역행이라 하지 않는다).
    """
    if has_commentary:
        return "ready"
    if (
        mode != "on_view"
        or not has_rows
        or selected_date is None
        or selected_strategy != default_strategy
    ):
        return "off"
    key = f"{selected_date.isoformat()}:{selected_strategy}"
    if key not in _commentary_inflight:
        _commentary_inflight.add(key)
        schedule(key)
    return "generating"


async def _lazy_commentary(key: str, analysis_date: Date, strategy_name: str) -> None:
    from backend.app.services.batch.daily_report import (
        generate_and_store_commentary,
    )

    try:
        await generate_and_store_commentary(analysis_date, strategy_name)
    finally:
        _commentary_inflight.discard(key)


@router.get("/undervalued", response_model=ApiEnvelope[UndervaluedResponse])
async def get_undervalued(
    background_tasks: BackgroundTasks,
    analysis_date: Date | None = Query(default=None, alias="date"),
    strategy_name: str | None = Query(default=None),
    service_session: AsyncSession = Depends(get_service_session),
    research_session: AsyncSession = Depends(get_research_session),
) -> ApiEnvelope[UndervaluedResponse]:
    selected_strategy = strategy_name or settings.DEFAULT_STRATEGY_NAME
    selected_date = analysis_date or await _latest_analysis_date(
        service_session,
        selected_strategy,
    )
    if selected_date is None:
        return ApiEnvelope(
            data=UndervaluedResponse(
                analysis_date=None,
                strategy_name=selected_strategy,
                items=[],
            ),
            error=None,
        )

    result = await service_session.execute(
        select(BatchAnalysisResult)
        .where(BatchAnalysisResult.analysis_date == selected_date)
        .where(BatchAnalysisResult.strategy_name == selected_strategy)
        .order_by(BatchAnalysisResult.rank)
    )
    rows = list(result.scalars())
    stock_meta = await _stock_meta(
        research_session,
        [row.stock_code for row in rows],
    )
    items = [
        UndervaluedStockResponse(
            rank=row.rank,
            stock_code=row.stock_code,
            name=stock_meta.get(row.stock_code, {}).get("name"),
            market=stock_meta.get(row.stock_code, {}).get("market"),
            sector=stock_meta.get(row.stock_code, {}).get("sector"),
            score=float(row.score),
            llm_commentary=row.llm_commentary,
        )
        for row in rows
    ]
    from backend.app.services.batch.daily_report import llm_commentary_mode

    status = _commentary_status_and_maybe_schedule(
        mode=await llm_commentary_mode(),
        selected_strategy=selected_strategy,
        default_strategy=settings.DEFAULT_STRATEGY_NAME,
        selected_date=selected_date,
        has_commentary=any(row.llm_commentary for row in rows),
        has_rows=bool(rows),
        schedule=lambda key: background_tasks.add_task(
            _lazy_commentary, key, selected_date, selected_strategy
        ),
    )
    return ApiEnvelope(
        data=UndervaluedResponse(
            analysis_date=selected_date,
            strategy_name=selected_strategy,
            items=items,
            commentary_status=status,
        ),
        error=None,
    )


async def _latest_analysis_date(
    session: AsyncSession,
    strategy_name: str,
) -> Date | None:
    result = await session.execute(
        select(func.max(BatchAnalysisResult.analysis_date)).where(
            BatchAnalysisResult.strategy_name == strategy_name
        )
    )
    return result.scalar_one_or_none()


async def _stock_meta(
    session: AsyncSession,
    codes: list[str],
) -> dict[str, dict[str, str | None]]:
    if not codes:
        return {}
    result = await session.execute(select(Stock).where(Stock.code.in_(codes)))
    meta = {
        stock.code: {
            "name": stock.name,
            "market": stock.market,
            "sector": stock.sector,
        }
        for stock in result.scalars()
    }
    # US 티커는 stocks가 아니라 stocks_us에 있다(ORM 모델 없는 애드혹 테이블).
    missing = [code for code in codes if code not in meta]
    if missing:
        placeholders = ",".join(f":c{i}" for i in range(len(missing)))
        rows = await session.execute(
            text(
                f"SELECT ticker, name, exchange, sector FROM stocks_us"
                f" WHERE ticker IN ({placeholders})"
            ),
            {f"c{i}": code for i, code in enumerate(missing)},
        )
        for ticker, name, exchange, sector in rows:
            meta[ticker] = {"name": name, "market": exchange, "sector": sector}
    return meta
