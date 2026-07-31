"""국면 인식 자동 분할 — 결정표·낙폭 계산·모드 해석."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from backend.app.services.accounts.auto_ramp import (
    AUTO_RAMP,
    auto_ramp_months,
    entry_drawdown,
    resolve_ramp_months,
)


# --- 결정표 (ramp study 결론 그대로) -------------------------------------------

@pytest.mark.parametrize("universe,dd,expected", [
    # US주식: 언제나 올인
    ("US_LARGE", -0.02, 1), ("US_LARGE", -0.10, 1), ("NASDAQ100", -0.30, 1),
    # US_ETF: 고점권만 3개월
    ("ETF_US", -0.02, 3), ("ETF_US", -0.08, 1), ("ETF_US", -0.20, 1),
    # KR주식: 급락 올인 / 조정 6 / 고점권 3
    ("KOSPI200", -0.30, 1), ("KOSPI200", -0.10, 6), ("KOSPI200", -0.01, 3),
    ("KOSDAQ_ALL", -0.10, 6),
    # KR_ETF: 조정만 6
    ("ETF_KR", -0.10, 6), ("ETF_KR", -0.02, 1), ("ETF_KR", -0.20, 1),
    # DC류: 급락 올인 / 그 외 3
    ("ETF_KR_DC_RISK", -0.30, 1), ("ETF_KR_DC_RISK", -0.10, 3),
    ("ETF_KR_DC_RISK", -0.01, 3),
])
def test_auto_ramp_decision_table(universe, dd, expected):
    assert auto_ramp_months(universe, dd) == expected


def test_auto_ramp_bucket_boundaries():
    # 경계: -5%는 조정, -15%는 급락 (버킷 [·) 규약)
    assert auto_ramp_months("KOSPI200", -0.05) == 6
    assert auto_ramp_months("KOSPI200", -0.15) == 1
    assert auto_ramp_months("KOSPI200", -0.0499) == 3


# --- entry_drawdown -------------------------------------------------------------

@pytest.fixture()
def dd_db(tmp_path: Path) -> Path:
    db = tmp_path / "research.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT, close REAL)"
        )
        conn.execute(
            "CREATE TABLE prices_daily_us (ticker TEXT, date TEXT, close REAL)"
        )
        # KR 대표(069500): 고점 100 → 현재 80 = -20%
        for d, px in [("2026-01-02", 100.0), ("2026-03-02", 90.0),
                      ("2026-06-30", 80.0)]:
            conn.execute(
                "INSERT INTO prices_daily VALUES ('069500', ?, ?)", (d, px)
            )
        # US 대표(SPY): 고점 500 → 현재 490 = -2%
        for d, px in [("2026-01-02", 500.0), ("2026-06-30", 490.0)]:
            conn.execute(
                "INSERT INTO prices_daily_us VALUES ('SPY', ?, ?)", (d, px)
            )
    return db


def test_entry_drawdown_kr_and_us(dd_db: Path):
    dd_kr = entry_drawdown("KOSPI200", as_of=date(2026, 7, 1), db_path=dd_db)
    assert dd_kr == pytest.approx(-0.20)
    dd_us = entry_drawdown("US_LARGE", as_of=date(2026, 7, 1), db_path=dd_db)
    assert dd_us == pytest.approx(-0.02)


def test_entry_drawdown_missing_data_defaults_zero(dd_db: Path):
    assert entry_drawdown("KOSPI200", as_of=date(2020, 1, 1), db_path=dd_db) == 0.0


# --- resolve_ramp_months --------------------------------------------------------

def test_resolve_manual_passthrough(dd_db: Path):
    assert resolve_ramp_months(
        6, "KOSPI200", enabled_at=datetime(2026, 7, 1), db_path=dd_db
    ) == 6
    assert resolve_ramp_months(
        0, "KOSPI200", enabled_at=datetime(2026, 7, 1), db_path=dd_db
    ) == 0


def test_resolve_auto_uses_decision_table(dd_db: Path):
    # AUTO(-1) + KR -20% 급락 → 올인(1)
    assert resolve_ramp_months(
        AUTO_RAMP, "KOSPI200", enabled_at=datetime(2026, 7, 1), db_path=dd_db
    ) == 1
    # AUTO + US 고점권 → US주식은 그래도 올인
    assert resolve_ramp_months(
        AUTO_RAMP, "US_LARGE", enabled_at=datetime(2026, 7, 1), db_path=dd_db
    ) == 1


def test_resolve_auto_without_enabled_at_is_lump(dd_db: Path):
    # ON 시각 미기록(레거시) — 보수적으로 올인(캡 없음)
    assert resolve_ramp_months(
        AUTO_RAMP, "KOSPI200", enabled_at=None, db_path=dd_db
    ) == 1
