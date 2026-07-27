"""Universe extensions: ETF_KR / ETF_US / KOSPI_TOP100 + price routing."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from research.backtest.engine import (
    _kospi_top_n_universe,
    _load_price_rows,
    get_universe,
)

AS_OF = date(2026, 6, 30)


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE stocks (code TEXT PRIMARY KEY, name TEXT, market TEXT,"
            " sector TEXT, industry TEXT, listed_at TEXT, delisted_at TEXT,"
            " is_delisted INTEGER DEFAULT 0)"
        )
        conn.executemany(
            "INSERT INTO stocks (code,name,market,listed_at,delisted_at) VALUES (?,?,?,?,?)",
            [
                ("069500", "KODEX 200", "ETF", "2002-10-14", None),
                ("132030", "KODEX 골드", "ETF", "2010-10-01", None),
                ("000001", "A", "KOSPI", "2000-01-01", None),
                ("000002", "B", "KOSPI", "2000-01-01", None),
                ("000003", "C", "KOSPI", "2000-01-01", None),
                ("000004", "D(상폐)", "KOSPI", "2000-01-01", "2025-01-01"),
                ("100001", "K", "KOSDAQ", "2000-01-01", None),
            ],
        )
        conn.execute(
            "CREATE TABLE market_caps (stock_code TEXT, date TEXT, market_cap NUMERIC,"
            " shares_outstanding INTEGER, PRIMARY KEY (stock_code, date))"
        )
        conn.executemany(
            "INSERT INTO market_caps VALUES (?,?,?,?)",
            [
                ("000001", "2026-06-30", 5.0e12, 1),
                ("000002", "2026-06-30", 9.0e12, 1),
                ("000003", "2026-06-30", 1.0e12, 1),
                ("000004", "2026-06-30", 8.0e12, 1),  # delisted → excluded
                ("100001", "2026-06-30", 7.0e12, 1),  # KOSDAQ → excluded
            ],
        )
        conn.execute(
            "CREATE TABLE stocks_us (ticker TEXT, name TEXT, exchange TEXT,"
            " sector TEXT, industry TEXT, currency TEXT, listed_at TEXT,"
            " delisted_at TEXT, is_delisted INTEGER DEFAULT 0)"
        )
        conn.executemany(
            "INSERT INTO stocks_us (ticker,name,exchange,currency,listed_at,is_delisted)"
            " VALUES (?,?,?,?,?,0)",
            [
                ("SPY", "SPDR S&P500", "ETF", "USD", "1993-01-29"),
                ("AAPL", "Apple", "NASDAQ", "USD", "1980-12-12"),
                ("JPM", "JPMorgan", "SP500", "USD", "1980-03-17"),
                ("ABNB", "Airbnb", "SP500", "USD", "2020-12-10"),  # post-IPO
            ],
        )
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT, close REAL, adj_close REAL)"
        )
        conn.execute(
            "INSERT INTO prices_daily VALUES ('069500','2026-06-30',130000,NULL)"
        )
        conn.execute(
            "CREATE TABLE prices_daily_us (ticker TEXT, date TEXT, close REAL, adj_close REAL)"
        )
        conn.execute(
            "INSERT INTO prices_daily_us VALUES ('SPY','2026-06-30',550.0,NULL)"
        )
    return path


def test_etf_kr_universe(db: Path) -> None:
    assert get_universe("ETF_KR", as_of=AS_OF, db_path=db) == ["069500", "132030"]


def test_etf_us_universe(db: Path) -> None:
    assert get_universe("ETF_US", as_of=AS_OF, db_path=db) == ["SPY"]


def test_us_large_unions_nasdaq_and_sp500_excludes_etf(db: Path) -> None:
    # NASDAQ (AAPL) ∪ SP500 (JPM, ABNB); ETF (SPY) excluded.
    assert set(get_universe("US_LARGE", as_of=AS_OF, db_path=db)) == {"AAPL", "JPM", "ABNB"}


def test_us_large_point_in_time_listing_excludes_pre_ipo(db: Path) -> None:
    # ABNB listed 2020-12-10 → absent from a 2015 universe.
    codes = get_universe("US_LARGE", as_of=date(2015, 1, 2), db_path=db)
    assert set(codes) == {"AAPL", "JPM"}
    assert "ABNB" not in codes


def test_kospi_top100_membership_point_in_time(db: Path) -> None:
    codes = get_universe("KOSPI_TOP100", as_of=AS_OF, db_path=db)
    # Delisted 000004 and KOSDAQ 100001 are excluded (set semantics; the
    # engine's scorer doesn't care about ordering).
    assert set(codes) == {"000001", "000002", "000003"}


def test_kospi_top_n_limit_picks_largest_caps(db: Path) -> None:
    top2 = _kospi_top_n_universe(as_of=AS_OF, db_path=db, top_n=2)
    # caps: 000002=9e12 > 000001=5e12 > 000003=1e12 → top2 keeps the largest two.
    assert set(top2) == {"000002", "000001"}


def test_kospi_top100_empty_without_caps(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE stocks (code TEXT, market TEXT, listed_at TEXT, delisted_at TEXT)")
    assert get_universe("KOSPI_TOP100", as_of=AS_OF, db_path=path) == []


def test_price_routing_etf_us_loads_us_only(db: Path) -> None:
    rows = _load_price_rows(date(2026, 6, 1), date(2026, 6, 30), db, "ETF_US")
    assert set(rows["stock_code"]) == {"SPY"}


def test_price_routing_etf_kr_loads_kr(db: Path) -> None:
    rows = _load_price_rows(date(2026, 6, 1), date(2026, 6, 30), db, "ETF_KR")
    assert set(rows["stock_code"]) == {"069500"}
