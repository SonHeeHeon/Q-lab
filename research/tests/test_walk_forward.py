"""Walk-forward re-optimization tests.

Previously walk_forward only recorded train windows and ran TEST windows with
the strategy's fixed weights — i.e. no walk-forward optimization at all. These
tests pin the new per-fold behavior: train-window optimization decides the
weights evaluated out-of-sample, defaults stay backward compatible.
"""

from __future__ import annotations

from datetime import date

import pytest

import research.backtest.walk_forward as wf
from research.backtest.engine import RunResult
from research.backtest.metrics import Metrics
from shared.domain.strategy import FactorWeight, StrategyDefinition


def _strategy(weight: float = -1.0) -> StrategyDefinition:
    return StrategyDefinition(
        name="wf_test",
        description="walk-forward test fixture",
        universe="KOSPI200",
        rebalance_freq="QUARTERLY",
        factors=[FactorWeight(factor="PER", weight=weight, transform="ZSCORE")],
        filters=[],
        top_n=5,
        start_date=date(2016, 1, 1),
        end_date=date(2022, 12, 31),
    )


def _fake_result(strategy: StrategyDefinition, sharpe: float = 0.0) -> RunResult:
    return RunResult(
        strategy_name=strategy.name,
        start_date=strategy.start_date,
        end_date=strategy.end_date,
        initial_nav=100.0,
        final_nav=100.0,
        equity_curve=[],
        trades=[],
        metrics=Metrics(
            cagr=0.0, mdd=0.0, sharpe=sharpe, sortino=0.0,
            win_rate=0.0, avg_holding_days=0.0, turnover=0.0, n_trades=0,
        ),
        warnings=[],
    )


def test_default_behavior_fixed_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[StrategyDefinition] = []

    def fake_run(strategy, db_path=None, **kwargs):
        calls.append(strategy)
        return _fake_result(strategy)

    monkeypatch.setattr(wf, "run_backtest", fake_run)
    result = wf.walk_forward(_strategy(), train_years=5, test_years=1, step_years=1)

    assert len(result.windows) == 2
    first, second = result.windows
    assert (first.train_start, first.train_end) == (date(2016, 1, 1), date(2021, 1, 1))
    assert (first.test_start, first.test_end) == (date(2021, 1, 2), date(2022, 1, 2))
    assert second.test_end == date(2022, 12, 31)  # clamped to strategy end
    # No optimization: OOS runs use the original weights.
    assert all(s.factors[0].weight == -1.0 for s in calls)
    assert all(w.test_factors[0].weight == -1.0 for w in result.windows)


def test_injected_optimizer_decides_oos_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    oos_runs: list[StrategyDefinition] = []
    train_strategies: list[StrategyDefinition] = []

    def fake_run(strategy, db_path=None, **kwargs):
        oos_runs.append(strategy)
        return _fake_result(strategy)

    def fake_optimizer(train_strategy: StrategyDefinition) -> StrategyDefinition:
        train_strategies.append(train_strategy)
        factors = [f.model_copy(update={"weight": 2.0}) for f in train_strategy.factors]
        return train_strategy.model_copy(update={"factors": factors}, deep=True)

    monkeypatch.setattr(wf, "run_backtest", fake_run)
    base = _strategy(weight=-1.0)
    result = wf.walk_forward(base, optimizer=fake_optimizer)

    # Optimizer saw TRAIN windows, not test windows.
    assert train_strategies[0].start_date == date(2016, 1, 1)
    assert train_strategies[0].end_date == date(2021, 1, 1)
    # OOS evaluation used the optimizer's weights, recorded on the window.
    assert all(s.factors[0].weight == 2.0 for s in oos_runs)
    assert all(w.test_factors[0].weight == 2.0 for w in result.windows)
    # Source strategy is never mutated.
    assert base.factors[0].weight == -1.0


def test_optimize_fold_converges_with_inmemory_optuna(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Objective peaks at weight=1.5; the seeded in-memory study must move the
    # weight toward it (and stay deterministic across runs).
    def fake_run(strategy, db_path=None, **kwargs):
        w = strategy.factors[0].weight
        return _fake_result(strategy, sharpe=-((w - 1.5) ** 2))

    monkeypatch.setattr(wf, "run_backtest", fake_run)
    optimized = wf._optimize_fold(
        _strategy(weight=-1.0), trials=20, objective="sharpe", db_path=None
    )
    assert abs(optimized.factors[0].weight - 1.5) < 1.0
