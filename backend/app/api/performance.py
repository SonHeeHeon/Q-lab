"""Performance-tracking REST API.

Compares a strategy's results across backtest / paper (모의투자) / real (실전투자):
- ``GET /api/performance/paper``   — PAPER account equity curve + metrics
- ``GET /api/performance/real``    — REAL account equity curve + metrics
- ``GET /api/performance/compare`` — all three side by side (the comparison view)
"""

from __future__ import annotations

from datetime import date as Date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.performance.service import (
    ModePerformance,
    load_account_performance,
    load_backtest_performance,
)
from research.backtest.benchmark import load_benchmark_close
from shared.db.session import get_research_session, get_service_session
from shared.domain.account import AccountType

router = APIRouter(prefix="/api/performance", tags=["performance"])


class PerfPoint(BaseModel):
    date: Date
    nav: float


class PerfMetrics(BaseModel):
    cagr: float
    mdd: float
    sharpe: float
    sortino: float
    win_rate: float
    total_return: float
    turnover: float
    n_trades: int


class ModePerformanceResponse(BaseModel):
    strategy: str
    mode: str  # PAPER | REAL | BACKTEST
    source: str  # BROKER_SNAPSHOT | RECONSTRUCTED | BACKTEST | EMPTY
    start_date: Date | None
    as_of: Date | None
    initial_nav: float | None
    current_nav: float | None
    equity_curve: list[PerfPoint]
    benchmark_curve: list[PerfPoint] | None = None
    metrics: PerfMetrics
    warnings: list[str] = []


class CompareResponse(BaseModel):
    strategy: str
    backtest: ModePerformanceResponse
    paper: ModePerformanceResponse
    real: ModePerformanceResponse


def _to_response(perf: ModePerformance) -> ModePerformanceResponse:
    return ModePerformanceResponse(
        strategy=perf.strategy,
        mode=perf.mode,
        source=perf.source,
        start_date=perf.start_date,
        as_of=perf.as_of,
        initial_nav=perf.initial_nav,
        current_nav=perf.current_nav,
        equity_curve=[PerfPoint(date=day, nav=nav) for day, nav in perf.equity_curve],
        benchmark_curve=_benchmark_points(perf),
        metrics=PerfMetrics(
            cagr=perf.metrics.cagr,
            mdd=perf.metrics.mdd,
            sharpe=perf.metrics.sharpe,
            sortino=perf.metrics.sortino,
            win_rate=perf.metrics.win_rate,
            total_return=perf.total_return,
            turnover=perf.metrics.turnover,
            n_trades=perf.metrics.n_trades,
        ),
        warnings=perf.warnings,
    )


def _benchmark_points(perf: ModePerformance) -> list[PerfPoint] | None:
    """KOSPI close series over the mode's window (for the overlay chart).

    None when the window is unknown or market_index has no coverage — the app
    simply skips the overlay.
    """
    if perf.start_date is None or perf.as_of is None:
        return None
    series = load_benchmark_close("KOSPI", perf.start_date, perf.as_of)
    if series.empty:
        return None
    return [
        PerfPoint(date=idx.date(), nav=float(value))
        for idx, value in series.items()
    ]


@router.get("/paper", response_model=ApiEnvelope[ModePerformanceResponse])
async def get_paper_performance(
    strategy: str | None = Query(default=None),
    initial_capital: float | None = Query(default=None),
    service_session: AsyncSession = Depends(get_service_session),
    research_session: AsyncSession = Depends(get_research_session),
) -> ApiEnvelope[ModePerformanceResponse]:
    name = strategy or settings.DEFAULT_STRATEGY_NAME
    perf = await load_account_performance(
        service_session,
        research_session,
        account_type=AccountType.PAPER,
        strategy=name,
        initial_capital=initial_capital,
    )
    return ApiEnvelope(data=_to_response(perf), error=None)


@router.get("/real", response_model=ApiEnvelope[ModePerformanceResponse])
async def get_real_performance(
    strategy: str | None = Query(default=None),
    initial_capital: float | None = Query(default=None),
    service_session: AsyncSession = Depends(get_service_session),
    research_session: AsyncSession = Depends(get_research_session),
) -> ApiEnvelope[ModePerformanceResponse]:
    name = strategy or settings.DEFAULT_STRATEGY_NAME
    perf = await load_account_performance(
        service_session,
        research_session,
        account_type=AccountType.REAL,
        strategy=name,
        initial_capital=initial_capital,
    )
    return ApiEnvelope(data=_to_response(perf), error=None)


@router.get("/compare", response_model=ApiEnvelope[CompareResponse])
async def get_compare_performance(
    strategy: str | None = Query(default=None),
    initial_capital: float | None = Query(default=None),
    service_session: AsyncSession = Depends(get_service_session),
    research_session: AsyncSession = Depends(get_research_session),
) -> ApiEnvelope[CompareResponse]:
    name = strategy or settings.DEFAULT_STRATEGY_NAME
    backtest = load_backtest_performance(name)
    paper = await load_account_performance(
        service_session,
        research_session,
        account_type=AccountType.PAPER,
        strategy=name,
        initial_capital=initial_capital,
    )
    real = await load_account_performance(
        service_session,
        research_session,
        account_type=AccountType.REAL,
        strategy=name,
        initial_capital=initial_capital,
    )
    return ApiEnvelope(
        data=CompareResponse(
            strategy=name,
            backtest=_to_response(backtest),
            paper=_to_response(paper),
            real=_to_response(real),
        ),
        error=None,
    )
