from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine

from research.backtest.engine import get_universe, run_backtest
from shared.db.models import Financial, PriceDaily, ResearchBase, Stock
from shared.domain.strategy import FactorWeight, StrategyDefinition


def test_backtest_engine_runs_on_point_in_time_value_data(tmp_path) -> None:
    db_path = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{db_path}")
    ResearchBase.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            Stock.__table__.insert(),
            [
                {
                    "code": "005930",
                    "name": "Samsung",
                    "market": "KOSPI",
                    "listed_at": date(2000, 1, 1),
                    "is_delisted": False,
                },
                {
                    "code": "000660",
                    "name": "SK Hynix",
                    "market": "KOSPI",
                    "listed_at": date(2000, 1, 1),
                    "is_delisted": False,
                },
            ],
        )
        conn.execute(
            PriceDaily.__table__.insert(),
            [
                _price("005930", date(2020, 1, 2), Decimal("100")),
                _price("000660", date(2020, 1, 2), Decimal("100")),
                _price("005930", date(2020, 2, 3), Decimal("110")),
                _price("000660", date(2020, 2, 3), Decimal("90")),
            ],
        )
        conn.execute(
            Financial.__table__.insert(),
            [
                {
                    "stock_code": "005930",
                    "fiscal_period": date(2019, 12, 31),
                    "disclosed_at": date(2020, 1, 1),
                    "eps": Decimal("10"),
                    "bps": Decimal("100"),
                },
                {
                    "stock_code": "000660",
                    "fiscal_period": date(2019, 12, 31),
                    "disclosed_at": date(2020, 1, 1),
                    "eps": Decimal("5"),
                    "bps": Decimal("100"),
                },
            ],
        )

    strategy = StrategyDefinition(
        name="smoke_value",
        description="low PER smoke strategy",
        universe="KOSPI200",
        rebalance_freq="MONTHLY",
        factors=[FactorWeight(factor="PER", weight=-1.0, transform="ZSCORE")],
        filters=[],
        top_n=1,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 28),
    )

    result = run_backtest(strategy, db_path=db_path)

    assert result.equity_curve
    assert result.metrics.n_trades >= 1
    assert {trade.code for trade in result.trades}


def test_get_universe_uses_point_in_time_index_memberships(tmp_path) -> None:
    db_path = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{db_path}")
    ResearchBase.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            Stock.__table__.insert(),
            [
                {
                    "code": "111111",
                    "name": "Kosdaq A",
                    "market": "KOSDAQ",
                    "listed_at": date(2000, 1, 1),
                    "is_delisted": False,
                },
                {
                    "code": "222222",
                    "name": "Kosdaq B",
                    "market": "KOSDAQ",
                    "listed_at": date(2000, 1, 1),
                    "is_delisted": False,
                },
            ],
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE index_memberships (
                index_code TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                valid_from DATE NOT NULL,
                valid_to DATE
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO index_memberships VALUES
              ('KOSDAQ150', '111111', '2020-01-01', '2020-06-01'),
              ('KOSDAQ150', '222222', '2020-06-01', NULL)
            """
        )

    assert get_universe("KOSDAQ150", as_of=date(2020, 3, 1), db_path=db_path) == ["111111"]
    assert get_universe("KOSDAQ150", as_of=date(2020, 7, 1), db_path=db_path) == ["222222"]


def test_backtest_engine_runs_on_us_tickers(tmp_path) -> None:
    db_path = tmp_path / "research.db"
    import sqlite3

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
        conn.execute("INSERT INTO stocks_us (ticker, name) VALUES ('AAPL', 'Apple')")
        conn.execute("INSERT INTO stocks_us (ticker, name) VALUES ('NVDA', 'Nvidia')")
        conn.executemany(
            """
            INSERT INTO prices_daily_us (
                ticker, date, open, high, low, close, volume, adj_close
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("AAPL", "2020-01-02", 100, 100, 100, 100, 1000, 100),
                ("NVDA", "2020-01-02", 100, 100, 100, 100, 1000, 100),
                ("AAPL", "2020-02-03", 110, 110, 110, 110, 1000, 110),
                ("NVDA", "2020-02-03", 90, 90, 90, 90, 1000, 90),
            ],
        )
        conn.executemany(
            """
            INSERT INTO financials_us (
                ticker, fiscal_period, disclosed_at, net_income, total_assets,
                total_equity, eps, bps
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("AAPL", "2019-12-31", "2020-01-01", 100, 1000, 500, 10, 50),
                ("NVDA", "2019-12-31", "2020-01-01", 50, 1000, 500, 5, 50),
            ],
        )
        conn.commit()

    strategy = StrategyDefinition(
        name="us_smoke",
        description="US ticker smoke strategy",
        universe="NASDAQ100",
        rebalance_freq="MONTHLY",
        factors=[FactorWeight(factor="PER", weight=-1.0, transform="ZSCORE")],
        filters=[],
        top_n=1,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 28),
    )

    result = run_backtest(strategy, db_path=db_path)

    assert result.equity_curve
    assert {trade.code for trade in result.trades} == {"AAPL"}


def _price(code: str, day: date, close: Decimal) -> dict[str, object]:
    return {
        "stock_code": code,
        "date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000,
        "adj_close": close,
    }
