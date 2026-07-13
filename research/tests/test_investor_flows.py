"""Investor-flow (수급) ingestion + factor tests.

Flow strength = trailing 20-day net purchase ÷ market cap, point-in-time.
The parser maps pykrx's Korean column names; the factor refuses to return
unnormalized values when caps are missing.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from research.backtest.engine import _factor_series
from research.data_ingestion.pykrx_loader import _investor_flow_rows_from_frame
from research.factors.flows import (
    calculate_foreign_net_20d,
    calculate_indiv_net_20d,
    calculate_inst_net_20d,
)

AS_OF = date(2026, 6, 30)


def _make_db(tmp_path: Path, *, with_caps: bool = True) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE investor_flows_daily (stock_code TEXT, date TEXT,"
            " foreign_net NUMERIC, inst_net NUMERIC, indiv_net NUMERIC,"
            " PRIMARY KEY (stock_code, date))"
        )
        # 25 trading days ending 6/30: foreign buys 1e9/day, inst sells 5e8/day.
        rows = []
        day = AS_OF
        added = 0
        while added < 25:
            if day.weekday() < 5:
                rows.append(("000001", day.isoformat(), 1e9, -5e8, -5e8))
                added += 1
            day -= timedelta(days=1)
        # A future row that must be excluded point-in-time.
        rows.append(("000001", (AS_OF + timedelta(days=1)).isoformat(), 1e12, 0, 0))
        conn.executemany(
            "INSERT INTO investor_flows_daily VALUES (?,?,?,?,?)", rows
        )
        if with_caps:
            conn.execute(
                "CREATE TABLE market_caps (stock_code TEXT, date TEXT,"
                " market_cap NUMERIC, shares_outstanding INTEGER,"
                " PRIMARY KEY (stock_code, date))"
            )
            conn.execute(
                "INSERT INTO market_caps VALUES ('000001', ?, 1e12, 1000000)",
                (AS_OF.isoformat(),),
            )
    return path


def test_foreign_strength_is_20d_sum_over_cap(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    series = calculate_foreign_net_20d(["000001"], as_of=AS_OF, db_path=db)
    # 20 most recent rows ≤ as_of: 20 × 1e9 = 2e10; cap 1e12 → 0.02 (2%).
    assert series["000001"] == pytest.approx(0.02)


def test_inst_strength_negative_for_net_selling(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    series = calculate_inst_net_20d(["000001"], as_of=AS_OF, db_path=db)
    assert series["000001"] == pytest.approx(-0.01)  # 20 × -5e8 ÷ 1e12


def test_indiv_strength_negative_for_net_selling(tmp_path: Path) -> None:
    # 개인 순매도(-5e8/day) fixture → 음수 강도. 역신호 팩터의 원시값 방향 검증.
    db = _make_db(tmp_path)
    series = calculate_indiv_net_20d(["000001"], as_of=AS_OF, db_path=db)
    assert series["000001"] == pytest.approx(-0.01)  # 20 × -5e8 ÷ 1e12


def test_engine_dispatch_indiv_flow_factor(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    series = _factor_series(
        "INDIV_NET_20D", ["000001"], as_of=AS_OF, db_path=db, warnings=[]
    )
    assert series["000001"] == pytest.approx(-0.01)


def test_na_without_market_cap_normalizer(tmp_path: Path) -> None:
    db = _make_db(tmp_path, with_caps=False)
    series = calculate_foreign_net_20d(["000001"], as_of=AS_OF, db_path=db)
    assert series.empty  # never returns raw unnormalized flow


def test_engine_dispatch_flow_factor(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    series = _factor_series(
        "FOREIGN_NET_20D", ["000001"], as_of=AS_OF, db_path=db, warnings=[]
    )
    assert series["000001"] == pytest.approx(0.02)


def test_parser_maps_pykrx_columns() -> None:
    df = pd.DataFrame(
        {
            "기관합계": [-5e8, float("nan")],
            "기타법인": [1e7, 1e7],
            "개인": [-5e8, 2e8],
            "외국인합계": [1e9, float("nan")],
            "전체": [0.0, 0.0],
        },
        index=pd.to_datetime(["2026-06-30", "2026-06-29"]),
    )
    rows = _investor_flow_rows_from_frame("000001", df)
    assert len(rows) == 2
    first = rows[0]
    assert first["date"] == date(2026, 6, 30)
    assert int(first["foreign_net"]) == int(1e9)
    assert int(first["inst_net"]) == int(-5e8)
    assert int(first["indiv_net"]) == int(-5e8)
    second = rows[1]
    assert second["foreign_net"] is None  # NaN → NULL, row kept (개인 present)
    assert int(second["indiv_net"]) == int(2e8)
