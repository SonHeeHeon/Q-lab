"""Tests for research/scripts/seed_kr_etfs.py — tmp sqlite only, injected
price_fn, no network, no real DB touched."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from research.scripts.seed_kr_etfs import read_curated_universe, seed_kr_etfs

START = date(2024, 1, 1)
END = date(2024, 1, 31)


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE stocks (code TEXT PRIMARY KEY, name TEXT, market TEXT,"
            " sector TEXT, industry TEXT, listed_at TEXT NOT NULL, delisted_at TEXT,"
            " is_delisted INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT NOT NULL REFERENCES stocks(code),"
            " date TEXT NOT NULL, open NUMERIC NOT NULL, high NUMERIC NOT NULL,"
            " low NUMERIC NOT NULL, close NUMERIC NOT NULL, volume INTEGER NOT NULL,"
            " adj_close NUMERIC, PRIMARY KEY (stock_code, date))"
        )
        conn.commit()
    return path


def _fake_frame() -> pd.DataFrame:
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {
            "시가": [100.0, 101.0],
            "고가": [110.0, 111.0],
            "저가": [90.0, 91.0],
            "종가": [105.0, 106.0],
            "거래량": [1000, 1100],
        },
        index=idx,
    )


def _make_price_fn(bad_code: str, *, empty: bool = False):
    def _fn(code: str, start: date, end: date) -> pd.DataFrame:
        if code == bad_code:
            if empty:
                return pd.DataFrame()
            raise RuntimeError("simulated fetch failure")
        return _fake_frame()

    return _fn


def test_read_curated_universe_parses_real_csv() -> None:
    rows = read_curated_universe()
    assert len(rows) >= 27
    codes = {row["code"] for row in rows}
    assert "069500" in codes
    kodex200 = next(row for row in rows if row["code"] == "069500")
    assert kodex200["name"]
    assert kodex200["category"]
    assert kodex200["tax_class"]


def test_seed_kr_etfs_good_codes_and_bad_code_skipped(tmp_db: Path) -> None:
    codes = ["069500", "229200", "114800"]
    result = seed_kr_etfs(
        codes=codes,
        start=START,
        end=END,
        db_path=tmp_db,
        price_fn=_make_price_fn("114800"),
    )

    assert set(result["seeded"]) == {"069500", "229200"}
    assert result["skipped"] == ["114800"]
    assert result["price_rows"] == 4

    with sqlite3.connect(tmp_db) as conn:
        stock_codes = {row[0] for row in conn.execute("SELECT code FROM stocks")}
        assert stock_codes == {"069500", "229200"}
        price_count = conn.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
        assert price_count == 4


def test_seed_kr_etfs_empty_frame_is_skipped_not_raise(tmp_db: Path) -> None:
    codes = ["069500", "091170"]
    result = seed_kr_etfs(
        codes=codes,
        start=START,
        end=END,
        db_path=tmp_db,
        price_fn=_make_price_fn("091170", empty=True),
    )

    assert result["seeded"] == ["069500"]
    assert result["skipped"] == ["091170"]

    with sqlite3.connect(tmp_db) as conn:
        stock_codes = {row[0] for row in conn.execute("SELECT code FROM stocks")}
        assert stock_codes == {"069500"}


def test_seed_kr_etfs_idempotent_rerun_inserts_zero_new(tmp_db: Path) -> None:
    codes = ["069500", "229200"]
    price_fn = _make_price_fn("__none__")

    first = seed_kr_etfs(
        codes=codes, start=START, end=END, db_path=tmp_db, price_fn=price_fn
    )
    assert first["price_rows"] == 4

    with sqlite3.connect(tmp_db) as conn:
        price_count_after_first = conn.execute(
            "SELECT COUNT(*) FROM prices_daily"
        ).fetchone()[0]
        stock_count_after_first = conn.execute(
            "SELECT COUNT(*) FROM stocks"
        ).fetchone()[0]

    seed_kr_etfs(codes=codes, start=START, end=END, db_path=tmp_db, price_fn=price_fn)

    with sqlite3.connect(tmp_db) as conn:
        price_count_after_second = conn.execute(
            "SELECT COUNT(*) FROM prices_daily"
        ).fetchone()[0]
        stock_count_after_second = conn.execute(
            "SELECT COUNT(*) FROM stocks"
        ).fetchone()[0]

    assert price_count_after_second == price_count_after_first
    assert stock_count_after_second == stock_count_after_first


def test_seed_kr_etfs_dry_run_writes_nothing(tmp_db: Path) -> None:
    codes = ["069500", "229200"]
    result = seed_kr_etfs(
        codes=codes,
        start=START,
        end=END,
        db_path=tmp_db,
        price_fn=_make_price_fn("__none__"),
        dry_run=True,
    )

    assert set(result["seeded"]) == {"069500", "229200"}
    assert result["skipped"] == []
    assert result["price_rows"] == 0

    with sqlite3.connect(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0] == 0
