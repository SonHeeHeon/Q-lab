"""Benchmark-relative metrics, per-market cost model, execution-lag option."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import research.backtest.engine as eng
from research.backtest.benchmark import benchmark_relative
from research.backtest.simulator import (
    US_COST_MODEL,
    default_cost_model_for_universe,
)
from shared.domain.strategy import StrategyDefinition


# --- benchmark_relative -------------------------------------------------------

def _curve_and_bench(n: int = 120, beta: float = 1.0, daily_edge: float = 0.0):
    rng = np.random.default_rng(7)
    rb = rng.normal(0.0005, 0.01, n)
    rp = beta * rb + daily_edge
    days = pd.bdate_range("2025-01-02", periods=n + 1)
    bench = pd.Series(100 * np.cumprod(np.r_[1.0, 1 + rb]), index=days)
    nav = 1e8 * np.cumprod(np.r_[1.0, 1 + rp])
    curve = [(d.date(), float(v)) for d, v in zip(days, nav)]
    return curve, bench


def test_beta_two_alpha_zero():
    curve, bench = _curve_and_bench(beta=2.0)
    rel = benchmark_relative(curve, bench)
    assert rel is not None
    assert rel.beta == pytest.approx(2.0, abs=0.05)
    assert rel.alpha_annual == pytest.approx(0.0, abs=0.02)


def test_constant_edge_shows_alpha_and_ir():
    curve, bench = _curve_and_bench(beta=1.0, daily_edge=0.001)
    rel = benchmark_relative(curve, bench)
    assert rel is not None
    assert rel.alpha_annual == pytest.approx(0.001 * 252, rel=0.15)
    assert rel.information_ratio > 1.0
    assert rel.benchmark_total_return != 0.0


def test_insufficient_overlap_returns_none():
    curve, bench = _curve_and_bench(n=10)
    assert benchmark_relative(curve, bench) is None


# --- cost model selection -----------------------------------------------------

def test_us_universes_get_us_costs():
    for uni in ("NASDAQ100", "ETF_US"):
        model = default_cost_model_for_universe(uni)
        assert model.sell_tax_rate == 0.0
        assert model == US_COST_MODEL


def test_kr_universes_keep_krx_costs():
    for uni in ("KOSPI200", "KOSPI_TOP100", "ETF_KR", "KOSDAQ150"):
        model = default_cost_model_for_universe(uni)
        assert model.sell_tax_rate == pytest.approx(0.0023)


# --- execution lag -------------------------------------------------------------

def _lag_strategy(lag: int) -> StrategyDefinition:
    return StrategyDefinition(
        name=f"lag{lag}",
        description="execution lag test",
        universe="KOSPI_ALL",
        rebalance_freq="MONTHLY",
        factors=[],
        filters=[],
        top_n=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 20),
        execution_lag_days=lag,
    )


@pytest.fixture()
def patched_engine(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Prices-only fixture DB + fixed selection (universe/scoring patched)."""
    import sqlite3

    db = tmp_path / "research.db"
    days = [date(2026, 1, 2) + timedelta(days=i) for i in range(12)]
    days = [d for d in days if d.weekday() < 5]
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT, close REAL, adj_close REAL)"
        )
        for i, d in enumerate(days):
            conn.execute(
                "INSERT INTO prices_daily VALUES ('000001', ?, ?, NULL)",
                (d.isoformat(), 100.0 + i),
            )

    monkeypatch.setattr(eng, "get_universe", lambda *a, **k: ["000001"])
    scored = pd.DataFrame({"score": [1.0]}, index=pd.Index(["000001"], name="code"))
    monkeypatch.setattr(eng, "score_stocks", lambda *a, **k: scored.copy())
    monkeypatch.setattr(eng, "apply_filters", lambda frame, *a, **k: frame)
    return db, days


def test_lag_zero_trades_on_signal_day(patched_engine):
    db, days = patched_engine
    result = eng.run_backtest(_lag_strategy(0), db_path=db)
    assert result.trades
    assert result.trades[0].date == days[0]


def test_lag_one_trades_next_trading_day(patched_engine):
    db, days = patched_engine
    result = eng.run_backtest(_lag_strategy(1), db_path=db)
    assert result.trades
    assert result.trades[0].date == days[1]  # signal on day0, fill on day1
    # Fill price is day1's close (101), not day0's (100).
    assert result.trades[0].price == pytest.approx(101.0 * 1.001)  # +10bp slippage
