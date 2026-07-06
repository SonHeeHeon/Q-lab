"""score_stocks grouped-vs-flat integration (qlab_alpha_v2 wiring).

Verifies the flat path is unchanged and the grouped path routes through the
composite scorer, using a fixture research DB with real factor tables.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from research.backtest.engine import score_stocks
from shared.domain.strategy import FactorGroup, FactorWeight, GroupFactor

AS_OF = date(2024, 6, 1)


@pytest.fixture()
def research_db(tmp_path: Path) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT,"
            " close REAL, adj_close REAL, volume INTEGER)"
        )
        conn.execute(
            "CREATE TABLE financials (id INTEGER PRIMARY KEY, stock_code TEXT,"
            " fiscal_period TEXT, disclosed_at TEXT, net_income REAL,"
            " total_equity REAL, total_assets REAL, eps REAL, bps REAL)"
        )
        # Four names with clearly different value/quality profiles.
        prices = []
        fins = []
        profile = {
            "000001": (5000.0, 3.0e12, 1.0e13),   # cheap, high ROE  → best
            "000002": (5000.0, 1.0e12, 1.0e13),   # cheap, low ROE
            "000003": (50000.0, 3.0e12, 1.0e13),  # pricey, high ROE
            "000004": (50000.0, 1.0e12, 1.0e13),  # pricey, low ROE  → worst
        }
        for code, (price, ni, eq) in profile.items():
            prices.append((code, "2024-05-31", price, None, 1000))
            # eps chosen so PER varies with price; shares 1e9.
            fins.append((code, "2023-12-31", "2024-03-15", ni, eq, 2.0e13, ni / 1e9, None))
        conn.executemany("INSERT INTO prices_daily VALUES (?,?,?,?,?)", prices)
        conn.executemany(
            "INSERT INTO financials (stock_code, fiscal_period, disclosed_at,"
            " net_income, total_equity, total_assets, eps, bps) VALUES (?,?,?,?,?,?,?,?)",
            fins,
        )
    return path


def test_flat_path_unchanged(research_db: Path) -> None:
    scored = score_stocks(
        ["000001", "000002", "000003", "000004"],
        [FactorWeight(factor="ROE", weight=1.0, transform="ZSCORE")],
        as_of=AS_OF,
        db_path=research_db,
    )
    assert "score" in scored.columns
    # High-ROE names rank above low-ROE names.
    order = list(scored.index)
    assert order.index("000001") < order.index("000002")


def test_grouped_path_routes_through_composite(research_db: Path) -> None:
    groups = [
        FactorGroup(
            name="Value",
            weight=0.5,
            factors=[GroupFactor(factor="PER", higher_is_better=False)],
        ),
        FactorGroup(
            name="Quality",
            weight=0.5,
            factors=[GroupFactor(factor="ROE", higher_is_better=True)],
        ),
    ]
    scored = score_stocks(
        list(("000001", "000002", "000003", "000004")),
        [],
        as_of=AS_OF,
        db_path=research_db,
        groups=groups,
        min_groups=2,
    )
    # cheap+high-ROE tops, pricey+low-ROE bottoms; middles in between.
    order = list(scored.index)
    assert order[0] == "000001"
    assert order[-1] == "000004"
    assert set(order) == {"000001", "000002", "000003", "000004"}


def test_grouped_min_groups_excludes_incomplete(research_db: Path) -> None:
    # Require 3 groups but only 2 exist → everyone dropped (score NaN).
    groups = [
        FactorGroup(name="Value", weight=0.5, factors=[GroupFactor(factor="PER", higher_is_better=False)]),
        FactorGroup(name="Quality", weight=0.5, factors=[GroupFactor(factor="ROE")]),
    ]
    scored = score_stocks(
        ["000001", "000002"], [], as_of=AS_OF, db_path=research_db,
        groups=groups, min_groups=3,
    )
    assert scored.empty
