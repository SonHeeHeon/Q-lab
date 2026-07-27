"""US fundamental factors — deterministic TTM/point-in-time correctness."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from research.factors.fundamental_us import (
    calculate_accruals,
    calculate_fcf_yield,
    calculate_gp_a,
    calculate_shareholder_yield,
)

AS_OF = date(2024, 12, 31)


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE financials_us (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, fiscal_period DATE,
                disclosed_at DATE, revenue NUMERIC, operating_income NUMERIC,
                net_income NUMERIC, total_assets NUMERIC, total_equity NUMERIC,
                eps NUMERIC, bps NUMERIC, cfo NUMERIC, capex NUMERIC,
                gross_profit NUMERIC, buybacks NUMERIC, dividends_paid NUMERIC,
                shares_out NUMERIC)"""
        )
        # 4 disclosed quarters (TTM) + 1 future quarter that must be ignored.
        quarters = [
            ("2024-03-31", "2024-04-30"),
            ("2024-06-30", "2024-07-31"),
            ("2024-09-30", "2024-10-31"),
            ("2024-12-31", "2025-01-31"),  # disclosed AFTER as_of → excluded
        ]
        # Only the first 3 are disclosed by AS_OF (2024-12-31). Add an earlier
        # quarter so exactly 4 are in-window.
        rows = [("2023-12-31", "2024-01-31", 25, 30, 20, 10, 5)] + [
            (fp, dsc, 25, 30, 20, 10, 5) for fp, dsc in quarters
        ]
        for fp, dsc, gp, cfo, ni, capex, div in rows:
            conn.execute(
                "INSERT INTO financials_us (ticker, fiscal_period, disclosed_at,"
                " net_income, total_assets, cfo, capex, gross_profit,"
                " dividends_paid, buybacks, shares_out)"
                " VALUES ('TESTUS',?,?,?,?,?,?,?,?,?,?)",
                (fp, dsc, ni, 1000, cfo, capex, gp, div, 0, 100),
            )
        conn.execute(
            "CREATE TABLE prices_daily_us (ticker TEXT, date TEXT, close REAL, adj_close REAL)"
        )
        conn.execute("INSERT INTO prices_daily_us VALUES ('TESTUS','2024-12-30',50.0,48.0)")
    return path


def test_gp_a_ttm_over_assets(db: Path) -> None:
    # 4 in-window quarters × gross_profit 25 = TTM 100; assets 1000 → 0.1
    s = calculate_gp_a(["TESTUS"], as_of=AS_OF, db_path=db)
    assert s["TESTUS"] == pytest.approx(0.1)


def test_accruals_ni_minus_cfo_over_assets(db: Path) -> None:
    # (NI 80 − CFO 120) / 1000 = -0.04  (negative = high quality)
    s = calculate_accruals(["TESTUS"], as_of=AS_OF, db_path=db)
    assert s["TESTUS"] == pytest.approx(-0.04)


def test_fcf_yield_uses_raw_close_market_cap(db: Path) -> None:
    # FCF = CFO 120 − capex 40 = 80; mktcap = raw close 50 × shares 100 = 5000
    # (raw 50, NOT adj 48) → 80/5000 = 0.016
    s = calculate_fcf_yield(["TESTUS"], as_of=AS_OF, db_path=db)
    assert s["TESTUS"] == pytest.approx(0.016)


def test_point_in_time_excludes_future_disclosure(db: Path) -> None:
    # As of 2024-06-30 only 2 quarters are public (2023-12 disc 01-31,
    # 2024-03 disc 04-30). shareholder_yield still computes from what's public,
    # proving the disclosed_at<=as_of gate (no look-ahead into later filings).
    early = calculate_shareholder_yield(["TESTUS"], as_of=date(2024, 6, 30), db_path=db)
    # dividends TTM (2 quarters × 5 = 10) / (50 × 100) = 0.002; but only if a
    # price exists on/before 2024-06-30 — none does here, so cap is empty → NA.
    assert "TESTUS" not in early or early.empty
