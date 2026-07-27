"""Multi-sleeve portfolio backtest: blend + weight-optimization tests.

Synthetic curves throughout (no real backtest) except where noted — mirrors
the monkeypatched-engine pattern from test_walk_forward.py / test_after_tax.py:
``run_backtest`` is monkeypatched on the ``portfolio`` module to return
pre-built ``RunResult`` objects so Optuna trials run fast without a real DB.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

import research.backtest.portfolio as portfolio
from research.backtest.engine import EquityPoint, RunResult
from research.backtest.metrics import compute_metrics
from shared.domain.strategy import StrategyDefinition


def _curve(dates: list[date], values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.to_datetime(dates), dtype="float64")


def _strategy(name: str, universe: str = "KOSPI200") -> StrategyDefinition:
    return StrategyDefinition(
        name=name,
        description=name,
        universe=universe,
        rebalance_freq="QUARTERLY",
        factors=[],
        filters=[],
        top_n=5,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
    )


# ---------------------------------------------------------------------------
# normalize_curve
# ---------------------------------------------------------------------------


def test_normalize_curve_first_value_is_one_with_equity_points():
    curve = [
        EquityPoint(date=date(2020, 1, 1), nav=100.0),
        EquityPoint(date=date(2020, 1, 2), nav=110.0),
    ]
    series = portfolio.normalize_curve(curve)
    assert series.iloc[0] == pytest.approx(1.0)
    assert series.iloc[1] == pytest.approx(1.1)


def test_normalize_curve_first_value_is_one_with_tuples():
    curve = [(date(2020, 1, 1), 200.0), (date(2020, 1, 2), 150.0)]
    series = portfolio.normalize_curve(curve)
    assert series.iloc[0] == pytest.approx(1.0)
    assert series.iloc[1] == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# blend_curves
# ---------------------------------------------------------------------------


def test_blend_curves_buy_and_hold_50_50():
    dates = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]
    a = _curve(dates, [1.0, 1.1, 1.2])
    b = _curve(dates, [1.0, 0.9, 0.8])
    blended = portfolio.blend_curves([a, b], [0.5, 0.5], rebalance=None, base_nav=100.0)

    expected = [
        100.0 * (0.5 * av + 0.5 * bv)
        for av, bv in zip([1.0, 1.1, 1.2], [1.0, 0.9, 0.8])
    ]
    assert [d for d, _ in blended] == dates
    for (_, actual), exp in zip(blended, expected):
        assert actual == pytest.approx(exp)


def test_blend_curves_weights_one_zero_equals_curve_a():
    dates = [date(2020, 1, 1), date(2020, 1, 2)]
    a = _curve(dates, [1.0, 1.05])
    b = _curve(dates, [1.0, 0.95])
    blended = portfolio.blend_curves([a, b], [1.0, 0.0], rebalance=None, base_nav=1.0)

    for (_, actual), expected in zip(blended, [1.0, 1.05]):
        assert actual == pytest.approx(expected)


def test_blend_curves_rebalance_vs_buy_hold_differ_when_curves_diverge():
    dates = [
        date(2020, 1, 1), date(2020, 1, 15), date(2020, 1, 31),
        date(2020, 2, 1), date(2020, 2, 15), date(2020, 2, 28),
    ]
    a = _curve(dates, [1.0, 1.2, 1.5, 1.5, 1.8, 2.2])
    b = _curve(dates, [1.0, 0.95, 0.9, 0.9, 0.85, 0.8])

    buy_hold = portfolio.blend_curves([a, b], [0.5, 0.5], rebalance=None, base_nav=1.0)
    rebalanced = portfolio.blend_curves(
        [a, b], [0.5, 0.5], rebalance="MONTHLY", base_nav=1.0
    )

    assert buy_hold[-1][1] != pytest.approx(rebalanced[-1][1])
    # Buy-hold lets the dominant sleeve's weight drift up (no reset), so it
    # ends ahead of the periodically-reset blend given a diverges from b.
    assert buy_hold[-1][1] > rebalanced[-1][1]


def test_compute_metrics_on_blended_curve_returns_finite_values():
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(60)]
    a = _curve(dates, [1.0 + 0.001 * i for i in range(60)])
    b = _curve(dates, [1.0 - 0.0005 * i for i in range(60)])
    blended = portfolio.blend_curves(
        [a, b], [0.6, 0.4], rebalance="QUARTERLY", base_nav=1_000_000.0
    )
    metrics = compute_metrics(blended, [])
    assert math.isfinite(metrics.cagr)
    assert math.isfinite(metrics.mdd)
    assert math.isfinite(metrics.sharpe)


# ---------------------------------------------------------------------------
# optimize_sleeve_weights (monkeypatched engine — no real DB)
# ---------------------------------------------------------------------------


def _fake_run_result(name: str, dates: list[date], navs: list[float]) -> RunResult:
    equity_curve = [EquityPoint(date=d, nav=v) for d, v in zip(dates, navs)]
    metrics = compute_metrics(list(zip(dates, navs)), [])
    return RunResult(
        strategy_name=name,
        start_date=dates[0],
        end_date=dates[-1],
        initial_nav=navs[0],
        final_nav=navs[-1],
        equity_curve=equity_curve,
        trades=[],
        metrics=metrics,
        warnings=[],
    )


@pytest.fixture()
def dominant_and_weak_results() -> dict[str, RunResult]:
    dates = [d.date() for d in pd.bdate_range("2020-01-01", periods=252)]

    # Monotonic growth, zero drawdown -> calmar == cagr (large, positive).
    dominant_navs = [100.0 + i * (100.0 / 251) for i in range(252)]

    # Deep drawdown then partial recovery, ends below start -> negative cagr,
    # -50% mdd -> calmar strongly negative. Clearly dominated by "dominant".
    half = 252 // 2
    weak_navs = []
    for i in range(252):
        if i <= half:
            weak_navs.append(100.0 - 50.0 * i / half)
        else:
            j = i - half
            weak_navs.append(50.0 + 20.0 * j / (252 - half - 1))

    return {
        "dominant": _fake_run_result("dominant", dates, dominant_navs),
        "weak": _fake_run_result("weak", dates, weak_navs),
    }


def test_optimize_sleeve_weights_favors_dominant_sleeve_on_calmar(
    monkeypatch: pytest.MonkeyPatch, dominant_and_weak_results: dict[str, RunResult]
) -> None:
    def fake_run_backtest(strategy, *, db_path=None, tax_model=None, **kwargs):
        return dominant_and_weak_results[strategy.name]

    monkeypatch.setattr(portfolio, "run_backtest", fake_run_backtest)

    strategies = [_strategy("dominant"), _strategy("weak")]
    result = portfolio.optimize_sleeve_weights(
        strategies, objective="calmar", trials=30, rebalance="QUARTERLY"
    )

    assert sum(result["weights"]) == pytest.approx(1.0)
    assert result["weights"][0] > result["weights"][1]
    assert result["trials"] == 30
    assert result["objective"] == "calmar"
    assert math.isfinite(result["value"])
