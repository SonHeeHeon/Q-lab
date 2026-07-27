"""KRW 관점(krw_view) 환산 — US 슬리브 곡선에만 USDKRW 반영."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from research.backtest.portfolio import _usdkrw_index, apply_krw_view


def _curve(vals: list[float], start: date = date(2024, 1, 1)) -> pd.Series:
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(vals, index=idx, dtype="float64")


def _fx(vals: list[float], start: date = date(2024, 1, 1)) -> pd.Series:
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(vals, index=idx, dtype="float64")


def test_us_curve_scaled_by_fx_ratio():
    curve = _curve([1.0, 1.0, 1.0, 1.0])       # USD 곡선은 횡보
    fx = _fx([1300.0, 1300.0, 1430.0, 1560.0])  # 원화 약세 +10%/+20%
    out = apply_krw_view(curve, "US_LARGE", fx)
    # KRW 관점: 환율 상승분이 그대로 수익
    assert out.iloc[-1] == pytest.approx(1.2)
    assert out.iloc[2] == pytest.approx(1.1)


def test_kr_universe_untouched():
    curve = _curve([1.0, 1.1, 1.2])
    fx = _fx([1300.0, 1400.0, 1500.0])
    out = apply_krw_view(curve, "KOSPI200", fx)
    assert out.equals(curve)


def test_missing_fx_passthrough():
    curve = _curve([1.0, 1.1])
    out = apply_krw_view(curve, "US_LARGE", pd.Series(dtype="float64"))
    assert out.equals(curve)


def test_usdkrw_index_reads_market_index(tmp_path: Path):
    db = tmp_path / "research.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE market_index (index_code TEXT, date TEXT, close REAL)"
        )
        conn.executemany(
            "INSERT INTO market_index VALUES ('USDKRW', ?, ?)",
            [("2024-01-02", 1300.0), ("2024-01-03", 1310.0)],
        )
        conn.execute("INSERT INTO market_index VALUES ('KOSPI', '2024-01-02', 2600)")
    fx = _usdkrw_index(db)
    assert len(fx) == 2 and fx.iloc[0] == 1300.0  # KOSPI 행은 제외
