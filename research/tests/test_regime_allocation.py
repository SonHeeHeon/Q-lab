"""Regime exposure integration into allocation + macro_data reader."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from research.backtest.engine import _allocate_equal_weight
from research.backtest.macro_data import load_regime_series


def test_exposure_scales_budget():
    prices = {"A": 100.0, "B": 100.0}
    full = _allocate_equal_weight(["A", "B"], nav=1_000_000, prices=prices, exposure=1.0)
    half = _allocate_equal_weight(["A", "B"], nav=1_000_000, prices=prices, exposure=0.5)
    # 995,000 invested / 2 / 100 = 4975 full; half ≈ 2487.
    assert full["A"] == 4975
    assert half["A"] == 2487


def test_crisis_exposure_holds_all_cash():
    target = _allocate_equal_weight(
        ["A"], nav=1_000_000, prices={"A": 100.0}, exposure=0.0
    )
    assert target == {}  # nothing bought → 100% cash


def test_load_regime_series_reads_market_index(tmp_path: Path):
    db = tmp_path / "research.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE market_index (index_code TEXT, date TEXT, close NUMERIC,"
            " PRIMARY KEY (index_code, date))"
        )
        conn.executemany(
            "INSERT INTO market_index VALUES (?,?,?)",
            [
                ("KOSPI", "2026-07-01", 2500.0),
                ("KOSPI", "2026-07-02", 2510.0),
                ("VIX", "2026-07-02", 15.0),
                ("USDKRW", "2026-07-02", 1300.0),
                ("US10Y", "2026-07-02", 4.2),
                ("VIX", "2026-08-01", 99.0),  # future → excluded
            ],
        )
    series = load_regime_series(date(2026, 7, 2), db_path=db)
    assert set(series) == {"kospi", "us10y", "usdkrw", "vix"}
    assert len(series["kospi"]) == 2
    assert series["vix"].iloc[-1] == 15.0  # future 99.0 excluded point-in-time


def test_load_regime_series_missing_table(tmp_path: Path):
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    assert load_regime_series(date(2026, 7, 2), db_path=db) == {}
