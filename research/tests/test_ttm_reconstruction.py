"""TTM net-income reconstruction tests (KR annual/interim double-count fix).

KR/DART rows mix 12-month annual reports with their own 3-month interim
reports; the old "sum the last 4 disclosures" TTM double-counted up to ~2x
(e.g. Samsung at 2024-06-01: 29.80T vs true 20.67T). Quarters are now
reconstructed (Q4 = annual − Q1..Q3) and PER shares the same 12-month basis.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from research.factors.quality import calculate_quality_factors
from research.factors.value import calculate_value_factors

AS_OF = date(2024, 6, 1)


def _make_db(tmp_path: Path) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE financials (id INTEGER PRIMARY KEY,"
            " stock_code TEXT, fiscal_period TEXT, disclosed_at TEXT,"
            " net_income REAL, total_equity REAL, total_assets REAL,"
            " eps REAL, bps REAL)"
        )
        conn.execute(
            "CREATE TABLE financials_us (id INTEGER PRIMARY KEY,"
            " ticker TEXT, fiscal_period TEXT, disclosed_at TEXT,"
            " net_income REAL, total_equity REAL, total_assets REAL,"
            " eps REAL, bps REAL)"
        )
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT,"
            " close REAL, adj_close REAL)"
        )
        kr_rows = [
            # 005930-like: real Samsung figures from the audit's verification.
            ("005930", "2023-03-31", "2023-05-15", 1.57e12, None, None, None, None),
            ("005930", "2023-06-30", "2023-08-14", 1.72e12, None, None, None, None),
            ("005930", "2023-09-30", "2023-11-14", 5.84e12, None, None, None, None),
            ("005930", "2023-12-31", "2024-03-12", 15.49e12, None, None, None, None),
            ("005930", "2024-03-31", "2024-05-16", 6.75e12, 3.6e14, 4.6e14, None, None),
            # 111111: annual-only history.
            ("111111", "2022-12-31", "2023-03-10", 2.0e12, 1.0e13, 2.0e13, None, None),
            ("111111", "2023-12-31", "2024-03-10", 3.0e12, 1.2e13, 2.2e13, None, None),
            # 222222: young listing, one quarter only.
            ("222222", "2024-03-31", "2024-05-10", 0.5e12, 4.0e12, 8.0e12, None, None),
            # 333333: PER basis case — latest is a Q1 interim with 3-month EPS.
            ("333333", "2025-03-31" , "2025-05-10", 0.9e12, None, None, None, None),
        ]
        # 333333 full history (prior-year interims + annual + latest Q1):
        kr_rows += [
            ("333333", "2025-06-30", "2025-08-10", 0.9e12, None, None, None, None),
            ("333333", "2025-09-30", "2025-11-10", 0.9e12, None, None, None, None),
            ("333333", "2025-12-31", "2026-03-10", 3.6e12, None, None, None, None),
            ("333333", "2026-03-31", "2026-05-10", 1.0e12, 2.0e12, 4.0e12, 1000.0, None),
        ]
        conn.executemany(
            "INSERT INTO financials (stock_code, fiscal_period, disclosed_at,"
            " net_income, total_equity, total_assets, eps, bps)"
            " VALUES (?,?,?,?,?,?,?,?)",
            kr_rows,
        )
        us_rows = [
            # Uniform quarterly flows — the Dec-31 row is a 3-month flow here.
            ("MSFT", "2023-06-30", "2023-07-30", 2.5e12, None, None, None, None),
            ("MSFT", "2023-09-30", "2023-10-30", 2.5e12, None, None, None, None),
            ("MSFT", "2023-12-31", "2024-01-30", 2.5e12, None, None, None, None),
            ("MSFT", "2024-03-31", "2024-04-30", 2.5e12, 5.0e13, 1.0e14, None, None),
        ]
        conn.executemany(
            "INSERT INTO financials_us (ticker, fiscal_period, disclosed_at,"
            " net_income, total_equity, total_assets, eps, bps)"
            " VALUES (?,?,?,?,?,?,?,?)",
            us_rows,
        )
        conn.executemany(
            "INSERT INTO prices_daily VALUES (?,?,?,?)",
            [("333333", "2026-06-30", 37_000.0, None)],
        )
    return path


def test_kr_ttm_reconstructs_quarters_no_double_count(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    frame = calculate_quality_factors(["005930"], as_of=AS_OF, db_path=db)
    # Q4-23 = 15.49 − (1.57+1.72+5.84) = 6.36 → TTM = 6.75+6.36+5.84+1.72 = 20.67T
    expected_roe = 20.67e12 / 3.6e14
    buggy_roe = 29.80e12 / 3.6e14  # old sum-of-last-4 (annual double-counted)
    roe = frame.loc["005930", "ROE"]
    assert roe == pytest.approx(expected_roe, rel=1e-6)
    assert abs(roe - buggy_roe) > 0.02  # clearly not the inflated figure


def test_kr_annual_only_uses_latest_annual(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    frame = calculate_quality_factors(["111111"], as_of=AS_OF, db_path=db)
    assert frame.loc["111111", "ROE"] == pytest.approx(3.0e12 / 1.2e13)


def test_kr_young_listing_single_quarter_not_inflated(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    frame = calculate_quality_factors(["222222"], as_of=AS_OF, db_path=db)
    assert frame.loc["222222", "ROE"] == pytest.approx(0.5e12 / 4.0e12)


def test_us_quarterly_flows_plain_sum(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    frame = calculate_quality_factors(["MSFT"], as_of=AS_OF, db_path=db)
    # Dec-31 row is a quarterly flow in the US table → plain 4-row sum = 10T.
    assert frame.loc["MSFT", "ROE"] == pytest.approx(1.0e13 / 5.0e13)


def test_per_uses_ttm_eps_when_latest_is_interim(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    frame = calculate_value_factors(
        ["333333"], as_of=date(2026, 6, 30), db_path=db
    )
    # TTM = Q1-26(1.0) + Q4-25(3.6−2.7=0.9) + Q3-25(0.9) + Q2-25(0.9) = 3.7T
    # shares = 1.0e12/1000 = 1e9 → eps_ttm = 3700 → PER = 37000/3700 = 10
    # (old behavior: PER = 37000/1000 = 37 on a 3-month EPS basis)
    assert frame.loc["333333", "PER"] == pytest.approx(10.0, rel=1e-6)
