from __future__ import annotations

import sqlite3
from datetime import date

from research.factors.quality import calculate_roe
from research.factors.value import calculate_pbr, calculate_per


def test_us_tickers_are_not_zero_padded_and_use_us_tables(tmp_path) -> None:
    db_path = tmp_path / "research.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE stocks_us (
                ticker TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT 'NASDAQ',
                sector TEXT,
                industry TEXT,
                currency TEXT NOT NULL DEFAULT 'USD',
                listed_at DATE,
                delisted_at DATE,
                is_delisted INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE prices_daily_us (
                ticker TEXT NOT NULL,
                date DATE NOT NULL,
                open NUMERIC NOT NULL,
                high NUMERIC NOT NULL,
                low NUMERIC NOT NULL,
                close NUMERIC NOT NULL,
                volume INTEGER NOT NULL DEFAULT 0,
                adj_close NUMERIC,
                currency TEXT NOT NULL DEFAULT 'USD',
                PRIMARY KEY (ticker, date)
            );
            CREATE TABLE financials_us (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                fiscal_period DATE NOT NULL,
                disclosed_at DATE NOT NULL,
                revenue NUMERIC,
                operating_income NUMERIC,
                net_income NUMERIC,
                total_assets NUMERIC,
                total_equity NUMERIC,
                eps NUMERIC,
                bps NUMERIC,
                currency TEXT NOT NULL DEFAULT 'USD',
                UNIQUE (ticker, fiscal_period)
            );
            """
        )
        conn.execute(
            "INSERT INTO stocks_us (ticker, name) VALUES ('AAPL', 'Apple Inc.')"
        )
        conn.execute(
            """
            INSERT INTO prices_daily_us (
                ticker, date, open, high, low, close, volume, adj_close
            )
            VALUES ('AAPL', '2026-01-15', 200, 200, 200, 200, 1000, 200)
            """
        )
        conn.execute(
            """
            INSERT INTO financials_us (
                ticker, fiscal_period, disclosed_at, net_income, total_assets,
                total_equity, eps, bps
            )
            VALUES (
                'AAPL', '2025-12-31', '2026-01-10', 100, 1000, 500, 10, 50
            )
            """
        )
        conn.commit()

    as_of = date(2026, 1, 31)

    assert calculate_per(["AAPL"], as_of=as_of, db_path=db_path).loc["AAPL"] == 20
    assert calculate_pbr(["AAPL"], as_of=as_of, db_path=db_path).loc["AAPL"] == 4
    assert calculate_roe(["AAPL"], as_of=as_of, db_path=db_path).loc["AAPL"] == 0.2
