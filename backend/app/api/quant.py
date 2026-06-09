"""Quant & AI REST API."""

from __future__ import annotations

from datetime import date as Date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
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


@router.get("/undervalued", response_model=ApiEnvelope[UndervaluedResponse])
async def get_undervalued(
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
    return ApiEnvelope(
        data=UndervaluedResponse(
            analysis_date=selected_date,
            strategy_name=selected_strategy,
            items=items,
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
    return {
        stock.code: {
            "name": stock.name,
            "market": stock.market,
            "sector": stock.sector,
        }
        for stock in result.scalars()
    }
