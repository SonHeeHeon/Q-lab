"""MARKET_CAP factor/filter correctness tests.

Previously MARKET_CAP silently used a close×volume turnover proxy, so a
"market cap >= 100B KRW" filter kept only the ~dozen highest-turnover names of
the day (12/193 on KOSPI200, measured on the real DB). MARKET_CAP now reads the
true market_caps table and, when the table is absent, returns empty so
apply_filters skips the rule with a warning instead of mis-filtering.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from research.backtest.engine import _factor_series, apply_filters
from research.data_ingestion.pykrx_loader import _market_cap_rows_from_frame
from shared.domain.strategy import FilterRule

AS_OF = date(2026, 6, 30)

# HIGHCAP: huge market cap, tiny volume (LG생활건강-like) — the bug's victim.
# LOWCAP: small cap, huge volume (theme stock) — the bug's false survivor.
HIGHCAP, LOWCAP = "000001", "000002"


def _make_db(tmp_path: Path, *, with_market_caps: bool) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT,"
            " close REAL, adj_close REAL, volume INTEGER)"
        )
        conn.executemany(
            "INSERT INTO prices_daily VALUES (?,?,?,?,?)",
            [
                (HIGHCAP, "2026-06-30", 500_000.0, None, 50_000),   # turnover 2.5e10
                (LOWCAP, "2026-06-30", 5_000.0, None, 90_000_000),  # turnover 4.5e11
            ],
        )
        if with_market_caps:
            conn.execute(
                "CREATE TABLE market_caps (stock_code TEXT, date TEXT,"
                " market_cap NUMERIC, shares_outstanding INTEGER,"
                " PRIMARY KEY (stock_code, date))"
            )
            conn.executemany(
                "INSERT INTO market_caps VALUES (?,?,?,?)",
                [
                    (HIGHCAP, "2026-06-28", 8.0e12, 16_000_000),  # 8T KRW
                    (HIGHCAP, "2026-06-30", 7.8e12, 16_000_000),
                    (LOWCAP, "2026-06-30", 5.0e10, 10_000_000),   # 50B KRW
                ],
            )
    return path


def test_market_cap_reads_true_caps_point_in_time(tmp_path: Path) -> None:
    db = _make_db(tmp_path, with_market_caps=True)
    series = _factor_series(
        "MARKET_CAP", [HIGHCAP, LOWCAP], as_of=AS_OF, db_path=db, warnings=[]
    )
    assert series[HIGHCAP] == pytest.approx(7.8e12)  # latest ≤ as_of, not 6/28
    assert series[LOWCAP] == pytest.approx(5.0e10)

    earlier = _factor_series(
        "MARKET_CAP", [HIGHCAP], as_of=date(2026, 6, 29), db_path=db, warnings=[]
    )
    assert earlier[HIGHCAP] == pytest.approx(8.0e12)  # point-in-time row


def test_filter_keeps_highcap_lowvolume_stock(tmp_path: Path) -> None:
    # The exact regression: 시총 1000억 필터가 고시총·저거래 종목을 살려야 한다.
    db = _make_db(tmp_path, with_market_caps=True)
    scored = pd.DataFrame({"score": [1.0, 2.0]}, index=[HIGHCAP, LOWCAP])
    scored.index.name = "code"
    result = apply_filters(
        scored,
        [FilterRule(field="market_cap", op="GTE", value=1e11)],
        as_of=AS_OF,
        db_path=db,
        warnings=[],
    )
    assert list(result.index) == [HIGHCAP]  # 8T passes, 50B dropped
    # Under the old turnover proxy this was inverted: LOWCAP(4.5e11) passed,
    # HIGHCAP(2.5e10) was dropped.


def test_filter_skipped_with_warning_when_table_absent(tmp_path: Path) -> None:
    db = _make_db(tmp_path, with_market_caps=False)
    warnings: list[str] = []
    scored = pd.DataFrame({"score": [1.0, 2.0]}, index=[HIGHCAP, LOWCAP])
    scored.index.name = "code"
    result = apply_filters(
        scored,
        [FilterRule(field="market_cap", op="GTE", value=1e11)],
        as_of=AS_OF,
        db_path=db,
        warnings=warnings,
    )
    assert len(result) == 2  # nobody mis-filtered
    assert any("MARKET_CAP data unavailable" in w for w in warnings)


def test_turnover_proxy_still_available(tmp_path: Path) -> None:
    db = _make_db(tmp_path, with_market_caps=False)
    series = _factor_series(
        "TURNOVER_PROXY", [HIGHCAP, LOWCAP], as_of=AS_OF, db_path=db, warnings=[]
    )
    assert series[HIGHCAP] == pytest.approx(500_000.0 * 50_000)
    assert series[LOWCAP] == pytest.approx(5_000.0 * 90_000_000)


def test_market_cap_rows_from_pykrx_frame() -> None:
    df = pd.DataFrame(
        {
            "시가총액": [8.0e12, float("nan")],
            "상장주식수": [16_000_000, 10_000_000],
        },
        index=pd.to_datetime(["2026-06-30", "2026-06-29"]),
    )
    rows = _market_cap_rows_from_frame("000001", df)
    assert len(rows) == 1  # NaN cap row skipped
    assert rows[0]["stock_code"] == "000001"
    assert rows[0]["date"] == date(2026, 6, 30)
    assert int(rows[0]["market_cap"]) == int(8.0e12)
    assert rows[0]["shares_outstanding"] == 16_000_000
