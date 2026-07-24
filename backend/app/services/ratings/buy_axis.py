"""매수축 등급 — 전략 유니버스 composite 백분위 → 매수 5단계(순수 계산).

DB 쓰기 없음, API 없음. ``get_universe``/``score_stocks``(research.backtest.engine)를
그대로 호출해 유니버스 + 추가 종목(extras)을 한 번에 스코어링하고, 그 결과 안에서
유니버스 전용 분포를 기준으로 백분위·등급을 매긴다.

``apply_filters``를 적용하지 않는 이유: 필터는 "매수 후보를 좁히는" 스크리닝
용도다. 등급은 보유·관심 종목이 필터에 걸려 제외되더라도 분포 안에 남아 있어야
정확한 백분위를 계산할 수 있으므로, 등급 계산에는 필터를 적용하지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date as Date

from backend.app.core.config import settings
from backend.app.services.batch.daily_analysis import (
    latest_research_price_date,
    load_strategy,
)
from research.backtest.engine import get_universe, score_stocks
from research.factors.common import normalize_code
from shared.db.session import research_db_path
from shared.domain.strategy import StrategyDefinition

EXTRAS_CAP = 50


@dataclass(frozen=True)
class BuyRating:
    code: str
    status: str  # 'OK' | 'NO_DATA' | 'UNSUPPORTED'
    buy_grade: str | None  # STRONG_BUY/BUY/NEUTRAL/REDUCE/AVOID (None unless OK)
    score: float | None
    percentile: float | None  # 1.0 = best, vs UNIVERSE-ONLY distribution
    weakest_group: str | None


@dataclass(frozen=True)
class BuyRatingsResult:
    as_of: str
    strategy_name: str
    universe_size: int
    ratings: list[BuyRating]
    warnings: list[str]


def resolve_rating_strategy(name: str | None) -> tuple[StrategyDefinition, str | None]:
    """이름으로 전략을 로드한다.

    요청한 이름의 전략 파일을 찾지 못하면(예: private 전략 yaml이 없는 OSS
    클론) ``settings.DEFAULT_STRATEGY_NAME``으로 폴백하고 경고 문자열을 함께
    반환한다. 이름 미지정·오탈자로 예외를 던지지 않는다.
    """

    requested = name or settings.DEFAULT_STRATEGY_NAME
    try:
        return load_strategy(requested), None
    except FileNotFoundError:
        fallback = settings.DEFAULT_STRATEGY_NAME
        if requested == fallback:
            raise
        warning = f"Strategy '{requested}' not found; falling back to '{fallback}'."
        return load_strategy(fallback), warning


def _quintile(percentile: float) -> str:
    if percentile >= 0.8:
        return "STRONG_BUY"
    if percentile >= 0.6:
        return "BUY"
    if percentile >= 0.4:
        return "NEUTRAL"
    if percentile >= 0.2:
        return "REDUCE"
    return "AVOID"


def compute_buy_ratings(
    strategy: StrategyDefinition,
    extra_codes: Iterable[str] = (),
    *,
    as_of: str | None = None,
    db_path=None,
) -> BuyRatingsResult:
    """전략 유니버스(+ extras)를 한 번에 스코어링해 매수 5등급을 매긴다."""

    resolved_db_path = db_path or research_db_path
    as_of_date: Date = Date.fromisoformat(as_of) if as_of else latest_research_price_date()

    warnings: list[str] = []
    universe = get_universe(strategy.universe, as_of=as_of_date, db_path=resolved_db_path)
    universe_set = set(universe)

    # extras 정규화 + 순서 보존 중복 제거
    seen: set[str] = set()
    normalized_extras: list[str] = []
    for raw in extra_codes:
        code = normalize_code(raw)
        if not code or code in seen:
            continue
        seen.add(code)
        normalized_extras.append(code)

    if len(normalized_extras) > EXTRAS_CAP:
        warnings.append(
            f"extra_codes truncated to {EXTRAS_CAP} (received {len(normalized_extras)})."
        )
        normalized_extras = normalized_extras[:EXTRAS_CAP]

    unsupported: dict[str, BuyRating] = {}
    kr_extra_codes: list[str] = []
    extras_order: list[str] = []
    for code in normalized_extras:
        if code in universe_set:
            continue  # 유니버스 통과분에서 이미 등급이 매겨짐
        extras_order.append(code)
        if code.isdigit():
            kr_extra_codes.append(code)
        else:
            unsupported[code] = BuyRating(
                code=code,
                status="UNSUPPORTED",
                buy_grade=None,
                score=None,
                percentile=None,
                weakest_group=None,
            )

    score_codes = list(universe) + kr_extra_codes
    frame = score_stocks(
        score_codes,
        strategy.factors,
        as_of=as_of_date,
        db_path=resolved_db_path,
        warnings=warnings,
        groups=strategy.groups,
        min_groups=strategy.min_groups,
        winsor_pct=strategy.winsor_pct,
        clip_z=strategy.clip_z,
    )

    has_weakest_group = "weakest_group" in frame.columns
    universe_scores = frame.loc[frame.index.isin(universe_set), "score"]
    universe_n = len(universe_scores)

    def _rate(code: str) -> BuyRating:
        if code not in frame.index:
            return BuyRating(
                code=code,
                status="NO_DATA",
                buy_grade=None,
                score=None,
                percentile=None,
                weakest_group=None,
            )
        row = frame.loc[code]
        score = float(row["score"])
        percentile = float((universe_scores < score).sum() / universe_n) if universe_n else 0.0
        weakest_group = row["weakest_group"] if has_weakest_group else None
        return BuyRating(
            code=code,
            status="OK",
            buy_grade=_quintile(percentile),
            score=score,
            percentile=percentile,
            weakest_group=weakest_group,
        )

    ratings = [_rate(code) for code in universe]
    for code in extras_order:
        ratings.append(unsupported[code] if code in unsupported else _rate(code))

    return BuyRatingsResult(
        as_of=as_of_date.isoformat(),
        strategy_name=strategy.name,
        universe_size=len(universe),
        ratings=ratings,
        warnings=warnings,
    )
