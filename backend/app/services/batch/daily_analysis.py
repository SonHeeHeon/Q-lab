"""Daily undervalued-stock analysis job."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import date as Date

import yaml
from sqlalchemy.dialects.sqlite import insert

from backend.app.core.config import PROJECT_ROOT, settings
from research.backtest.engine import apply_filters, get_universe, score_stocks
from shared.db.models import BatchAnalysisResult
from shared.db.session import research_db_path, service_session
from shared.domain.strategy import StrategyDefinition

STRATEGY_DIR = PROJECT_ROOT / "research" / "strategies"


@dataclass(frozen=True, slots=True)
class DailyAnalysisRow:
    analysis_date: Date
    strategy_name: str
    stock_code: str
    score: float
    rank: int


@dataclass(frozen=True, slots=True)
class DailyAnalysisResult:
    analysis_date: Date
    strategy_name: str
    rows: list[DailyAnalysisRow]


async def run_daily_analysis(
    *,
    analysis_date: Date | None = None,
    strategy_name: str | None = None,
    limit: int = 10,
) -> DailyAnalysisResult:
    """Score the configured strategy and persist the top candidates."""

    strategy = load_strategy(strategy_name or settings.DEFAULT_STRATEGY_NAME)
    as_of = analysis_date or latest_research_price_date()
    rows = await asyncio.to_thread(_score_top_rows, strategy, as_of, limit)
    await _persist_rows(rows)
    return DailyAnalysisResult(
        analysis_date=as_of,
        strategy_name=strategy.name,
        rows=rows,
    )


def load_strategy(strategy_name: str) -> StrategyDefinition:
    path = STRATEGY_DIR / f"{strategy_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Strategy file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    return StrategyDefinition.model_validate(payload)


def latest_research_price_date() -> Date:
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute("SELECT MAX(date) FROM prices_daily").fetchone()
    if row is None or row[0] is None:
        raise RuntimeError("No prices_daily rows found in research.db.")
    return Date.fromisoformat(str(row[0]))


def _score_top_rows(
    strategy: StrategyDefinition,
    as_of: Date,
    limit: int,
) -> list[DailyAnalysisRow]:
    warnings: list[str] = []
    universe = get_universe(strategy.universe, as_of=as_of, db_path=research_db_path)
    scored = score_stocks(
        universe,
        strategy.factors,
        as_of=as_of,
        db_path=research_db_path,
        warnings=warnings,
    )
    scored = apply_filters(
        scored,
        strategy.filters,
        as_of=as_of,
        db_path=research_db_path,
        warnings=warnings,
    )
    top = scored.head(limit)
    rows: list[DailyAnalysisRow] = []
    for rank, (stock_code, row) in enumerate(top.iterrows(), start=1):
        rows.append(
            DailyAnalysisRow(
                analysis_date=as_of,
                strategy_name=strategy.name,
                stock_code=str(stock_code).zfill(6),
                score=float(row["score"]),
                rank=rank,
            )
        )
    return rows


async def _persist_rows(rows: list[DailyAnalysisRow]) -> None:
    if not rows:
        return

    payload = [
        {
            "analysis_date": row.analysis_date,
            "strategy_name": row.strategy_name,
            "stock_code": row.stock_code,
            "score": row.score,
            "rank": row.rank,
            "llm_commentary": None,
        }
        for row in rows
    ]
    async with service_session() as session:
        stmt = insert(BatchAnalysisResult).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                BatchAnalysisResult.analysis_date,
                BatchAnalysisResult.strategy_name,
                BatchAnalysisResult.stock_code,
            ],
            set_={
                "score": stmt.excluded.score,
                "rank": stmt.excluded.rank,
                "llm_commentary": stmt.excluded.llm_commentary,
            },
        )
        await session.execute(stmt)
        await session.commit()
