from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine

from research.backtest.engine import run_backtest
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
