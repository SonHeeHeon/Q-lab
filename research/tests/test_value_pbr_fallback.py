"""KR PBR fallback derivation tests.

DART carries no BPS line item so ``financials.bps`` is NULL for KR — previously
PBR was permanently NA (dead weight in every value composite). value.py now
derives bps = total_equity / (net_income / eps) point-in-time. These tests pin
the derivation and its guards with a fixture research DB.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from research.factors.value import calculate_value_factors

AS_OF = date(2026, 6, 30)


@pytest.fixture()
def fixture_db(tmp_path: Path) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE prices_daily (
                stock_code TEXT, date TEXT,
                close REAL, adj_close REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE financials (
                id INTEGER PRIMARY KEY,
                stock_code TEXT, fiscal_period TEXT, disclosed_at TEXT,
                net_income REAL, total_equity REAL, eps REAL, bps REAL
            )
            """
        )
        prices = [
            ("000001", "2026-06-30", 70000.0, None),   # derived-bps case
            ("000002", "2026-06-30", 70000.0, None),   # explicit bps case
            ("000003", "2026-06-30", 10000.0, None),   # loss-maker, consistent signs
            ("000004", "2026-06-30", 10000.0, None),   # sign mismatch
            ("000005", "2026-06-30", 10000.0, None),   # equity missing
        ]
        conn.executemany(
            "INSERT INTO prices_daily VALUES (?,?,?,?)", prices
        )
        fins = [
            # (code, fiscal, disclosed, net_income, equity, eps, bps)
            ("000001", "2026-03-31", "2026-05-15", 5.0e12, 3.5e14, 5000.0, None),
            ("000002", "2026-03-31", "2026-05-15", 5.0e12, 3.5e14, 5000.0, 10000.0),
            ("000003", "2026-03-31", "2026-05-15", -1.0e11, 2.0e12, -100.0, None),
            ("000004", "2026-03-31", "2026-05-15", -1.0e11, 2.0e12, 100.0, None),
            ("000005", "2026-03-31", "2026-05-15", 5.0e12, None, 5000.0, None),
        ]
        conn.executemany(
            "INSERT INTO financials"
            " (stock_code, fiscal_period, disclosed_at, net_income, total_equity, eps, bps)"
            " VALUES (?,?,?,?,?,?,?)",
            fins,
        )
    return path


def test_pbr_derived_from_equity_when_bps_null(fixture_db: Path) -> None:
    frame = calculate_value_factors(["000001"], as_of=AS_OF, db_path=fixture_db)
    # shares = 5e12 / 5000 = 1e9 → bps = 3.5e14 / 1e9 = 350,000 → PBR = 70000/350000
    assert frame.loc["000001", "PBR"] == pytest.approx(0.2)
    assert frame.loc["000001", "PER"] == pytest.approx(14.0)


def test_explicit_bps_wins_over_derivation(fixture_db: Path) -> None:
    frame = calculate_value_factors(["000002"], as_of=AS_OF, db_path=fixture_db)
    # bps=10,000 stored → PBR = 7, not the derived 0.2
    assert frame.loc["000002", "PBR"] == pytest.approx(7.0)


def test_loss_maker_with_consistent_signs_gets_pbr(fixture_db: Path) -> None:
    frame = calculate_value_factors(["000003"], as_of=AS_OF, db_path=fixture_db)
    # shares = -1e11 / -100 = 1e9 → bps = 2e12/1e9 = 2000 → PBR = 5
    assert frame.loc["000003", "PBR"] == pytest.approx(5.0)
    assert pd.isna(frame.loc["000003", "PER"])  # eps <= 0 → PER NA


def test_sign_mismatch_yields_na(fixture_db: Path) -> None:
    frame = calculate_value_factors(["000004"], as_of=AS_OF, db_path=fixture_db)
    assert pd.isna(frame.loc["000004", "PBR"])  # negative share estimate rejected


def test_missing_equity_yields_na(fixture_db: Path) -> None:
    frame = calculate_value_factors(["000005"], as_of=AS_OF, db_path=fixture_db)
    assert pd.isna(frame.loc["000005", "PBR"])
