"""Daily undervalued-stock analysis job."""

from __future__ import annotations

import asyncio
import logging
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

logger = logging.getLogger(__name__)

STRATEGY_DIR = PROJECT_ROOT / "research" / "strategies"
# Personal tuned strategies live here and are gitignored — resolved FIRST so
# private equation weights never need to be committed for the app to use them.
PRIVATE_STRATEGY_DIR = STRATEGY_DIR / "private"


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


# 인사이트 4슬리브: (표시용 슬리브 키, 전략 이름). None = DEFAULT_STRATEGY_NAME
# (KR 주식). 전략은 load_strategy가 private/ 튜닝판을 우선 적용하므로, 같은
# 이름의 개인 튜닝이 있으면 자동으로 그 랭킹이 저장된다.
SLEEVE_INSIGHT_STRATEGIES: list[tuple[str, str | None]] = [
    ("kr_stock", None),
    ("kr_etf", "etf_rotation_kr"),
    ("us_stock", "us_stock_v1"),
    ("us_etf", "etf_rotation_us"),
    # DC 퇴직연금 위험 슬리브(자문 모드 — 월 1회 수동 리밸런스 참고).
    # 안전 슬리브는 단기채권 고정 보유 채택이라 랭킹 미노출(A/B: 로테이션 기각).
    ("dc_risk", "dc_risk_rotation_kr"),
]


async def run_weekly_sleeve_insights(*, limit: int = 10) -> dict:
    """주간 인사이트 — 4개 슬리브 전략 각각의 저평가(점수 상위) top-N을 저장.

    run_daily_analysis(=BatchAnalysisResult upsert)를 전략별로 반복할 뿐이라
    /api/quant/undervalued?strategy_name=... 조회가 그대로 동작한다. 한 슬리브
    실패(예: US 데이터 없음)가 나머지를 막지 않는다.
    """
    summary: dict[str, str] = {}
    for sleeve, strategy_name in SLEEVE_INSIGHT_STRATEGIES:
        try:
            result = await run_daily_analysis(
                strategy_name=strategy_name, limit=limit
            )
            summary[sleeve] = (
                f"{result.strategy_name}@{result.analysis_date} rows={len(result.rows)}"
            )
        except Exception as exc:  # noqa: BLE001 — 슬리브별 독립 실행
            logger.exception("weekly insights: %s sleeve failed", sleeve)
            summary[sleeve] = f"error: {exc}"
    logger.info("weekly sleeve insights %s", summary)
    return summary


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
    """Load a strategy by name — private (gitignored) dir wins over public."""
    candidates = [
        PRIVATE_STRATEGY_DIR / f"{strategy_name}.yaml",
        STRATEGY_DIR / f"{strategy_name}.yaml",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        raise FileNotFoundError(
            f"Strategy file not found: {strategy_name}.yaml "
            f"(looked in private/ and {STRATEGY_DIR})"
        )
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
        # 그룹 컴포짓 전략(etf_rotation_*, us_stock_v1, qlab_alpha_v2)은 factors가
        # 비어 있다 — groups를 넘기지 않으면 점수가 전부 비어 rows=0이 된다.
        groups=strategy.groups or None,
        min_groups=strategy.min_groups,
        winsor_pct=strategy.winsor_pct,
        clip_z=strategy.clip_z,
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
        code = str(stock_code)
        rows.append(
            DailyAnalysisRow(
                analysis_date=as_of,
                strategy_name=strategy.name,
                # 6자리 패딩은 KR 숫자 코드 전용 — US 티커(AAPL)에 적용하면
                # "00AAPL"로 오염된다(split_korean_and_global과 같은 규약).
                stock_code=code.zfill(6) if code.isdigit() else code,
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
