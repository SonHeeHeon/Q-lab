"""국면 인식 자동 분할(auto ramp) — ramp study(2026-07-31) 결정표의 코드화.

계좌의 ramp_in_months가 AUTO(-1)면, 퀀트 ON 시각의 시장 국면(대표 종목 1Y
고점대비 낙폭)과 슬리브 유니버스 분류로 분할 개월 수를 자동 결정한다.

결정표 근거(.omc/reports/2026-07-31_ramp-study.md, 7,140셀 롤링):
- 급락(≤-15%) 후 진입은 전 슬리브 올인이 우위.
- US 주식형은 어떤 국면에도 올인(분할이 중앙·최악 모두 손해).
- KR 주식형은 조정(-15~-5%)에서 6개월 분할이 중앙값 기준으로도 우위,
  고점권은 3개월(저비용 보험). KR ETF는 조정에서만 6개월.
- US ETF(GTAA)는 고점권에서만 3개월(승률 67%). DC류는 급락 외 3개월 무난.
결정은 ON 시각 기준으로 고정된다(램프 중 국면 변화에 흔들리지 않음).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date as Date
from datetime import datetime, timedelta
from pathlib import Path

from shared.db.session import research_db_path

logger = logging.getLogger(__name__)

AUTO_RAMP = -1  # account_profiles.ramp_in_months 센티널: 자동(상황 판단)

_US_STOCK = {"NASDAQ100", "US_LARGE", "US_ALL", "SP1500"}
_US_ETF = {"ETF_US"}
_KR_STOCK = {"KOSPI200", "KOSPI_TOP100", "KOSDAQ150", "KOSPI_ALL", "KOSDAQ_ALL"}
_KR_ETF = {"ETF_KR"}
_DC = {"ETF_KR_DC_RISK", "ETF_KR_DC_SAFE"}

# 국면 프록시 대표 종목: KR류·DC = KODEX200, US류 = SPY.
_KR_REF = "069500"
_US_REF = "SPY"


def auto_ramp_months(universe: str, drawdown: float) -> int:
    """(유니버스 분류, 고점대비 낙폭) → 분할 개월 수. 1 = 올인 (순수)."""
    u = universe.upper()
    crash = drawdown <= -0.15
    correction = -0.15 < drawdown <= -0.05
    if u in _US_STOCK:
        return 1
    if u in _US_ETF:
        return 1 if (crash or correction) else 3
    if u in _KR_STOCK:
        return 1 if crash else (6 if correction else 3)
    if u in _KR_ETF:
        return 6 if correction else 1
    if u in _DC:
        return 1 if crash else 3
    return 1  # 알 수 없는 유니버스 — 보수적으로 올인(캡 없음)


def entry_drawdown(
    universe: str, *, as_of: Date, db_path: Path | None = None
) -> float:
    """대표 종목 종가의 1Y 롤링 고점 대비 낙폭 (음수). 데이터 없으면 0.0.

    0.0(고점권 취급)은 안전한 기본값 — 결정표에서 가장 완만한 분할 또는
    올인으로 이어지며, 규정·매도에는 영향이 없다.
    """
    u = universe.upper()
    is_us = u in _US_STOCK or u in _US_ETF
    code = _US_REF if is_us else _KR_REF
    table, code_col = (
        ("prices_daily_us", "ticker") if is_us else ("prices_daily", "stock_code")
    )
    start = (as_of - timedelta(days=365)).isoformat()
    path = db_path or research_db_path
    try:
        with sqlite3.connect(path) as conn:
            rows = conn.execute(
                f"SELECT close FROM {table} WHERE {code_col} = ?"
                f" AND date >= ? AND date <= ? ORDER BY date",
                (code, start, as_of.isoformat()),
            ).fetchall()
    except sqlite3.Error:
        logger.warning("auto ramp: drawdown query failed (%s) — 0으로 처리", code)
        return 0.0
    closes = [float(r[0]) for r in rows if r[0]]
    if len(closes) < 2:
        logger.warning("auto ramp: %s 가격 부족 — 낙폭 0으로 처리", code)
        return 0.0
    peak = max(closes)
    return closes[-1] / peak - 1.0 if peak > 0 else 0.0


def resolve_ramp_months(
    profile_ramp: int,
    universe: str,
    *,
    enabled_at: datetime | None,
    db_path: Path | None = None,
) -> int:
    """계좌 설정값 → 실제 적용할 분할 개월 수.

    수동값(>=0)은 그대로. AUTO(-1)는 ON 시각의 국면으로 결정표 적용 —
    ON 시각 미기록(레거시)이면 보수적으로 올인(1).
    """
    if profile_ramp >= 0:
        return profile_ramp
    if enabled_at is None:
        return 1
    dd = entry_drawdown(universe, as_of=enabled_at.date(), db_path=db_path)
    months = auto_ramp_months(universe, dd)
    logger.info(
        "auto ramp: universe=%s dd=%.1f%% → %d개월", universe, dd * 100, months
    )
    return months
