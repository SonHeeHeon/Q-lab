"""Walk-forward validation for strategy robustness checks.

With ``optimize_trials > 0`` this performs true walk-forward optimization:
factor weights are re-optimized on each fold's TRAIN window (in-memory Optuna,
no report/study-file side effects) and only those weights are evaluated on the
out-of-sample TEST window. With the default ``optimize_trials=0`` it degrades
to the original fixed-weight OOS report (kept for backward compatibility, but
note that fixed weights measure only the given weights' robustness — they say
nothing about the optimization process being robust).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as Date
from pathlib import Path

from research.backtest.engine import RunResult, run_backtest
from shared.domain.strategy import FactorGroup, FactorWeight, StrategyDefinition


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    train_start: Date
    train_end: Date
    test_start: Date
    test_end: Date
    test_factors: list[FactorWeight] = field(default_factory=list)
    test_groups: list[FactorGroup] | None = None


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    results: list[RunResult]


def walk_forward(
    strategy: StrategyDefinition,
    train_years: int = 5,
    test_years: int = 1,
    step_years: int = 1,
    *,
    db_path: Path | None = None,
    optimize_trials: int = 0,
    objective: str = "sharpe",
    optimizer: Callable[[StrategyDefinition], StrategyDefinition] | None = None,
) -> WalkForwardResult:
    """Run rolling out-of-sample test windows across the strategy period.

    optimize_trials: Optuna trials per fold on the train window (0 = no
        re-optimization, original behavior).
    optimizer: override the per-fold optimizer — receives the TRAIN-window
        strategy and returns the strategy whose factors are used out-of-sample.
    """

    if train_years <= 0 or test_years <= 0 or step_years <= 0:
        raise ValueError("train_years, test_years, and step_years must be positive.")

    if optimizer is None and optimize_trials > 0:
        def optimizer(train_strategy: StrategyDefinition) -> StrategyDefinition:
            return _optimize_fold(
                train_strategy,
                trials=optimize_trials,
                objective=objective,
                db_path=db_path,
            )

    windows: list[WalkForwardWindow] = []
    results: list[RunResult] = []
    train_start = strategy.start_date

    while True:
        train_end = _add_years(train_start, train_years)
        test_start = _add_days(train_end, 1)
        test_end = _add_years(test_start, test_years)
        if test_start > strategy.end_date:
            break
        if test_end > strategy.end_date:
            test_end = strategy.end_date

        test_factors = [f.model_copy(deep=True) for f in strategy.factors]
        test_groups = (
            [g.model_copy(deep=True) for g in strategy.groups]
            if strategy.groups
            else strategy.groups
        )
        if optimizer is not None:
            train_strategy = strategy.model_copy(
                update={
                    "name": f"{strategy.name}_wf_train_{train_start.isoformat()}",
                    "start_date": train_start,
                    "end_date": train_end,
                },
                deep=True,
            )
            optimized = optimizer(train_strategy)
            test_factors = [f.model_copy(deep=True) for f in optimized.factors]
            # Grouped strategies tune GROUP weights — they must flow to the
            # OOS window too, or the whole optimization is a silent no-op.
            test_groups = (
                [g.model_copy(deep=True) for g in optimized.groups]
                if optimized.groups
                else optimized.groups
            )

        test_strategy = strategy.model_copy(
            update={
                "name": f"{strategy.name}_wf_{test_start.isoformat()}",
                "start_date": test_start,
                "end_date": test_end,
                "factors": test_factors,
                "groups": test_groups,
            },
            deep=True,
        )
        windows.append(
            WalkForwardWindow(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                test_factors=test_factors,
                test_groups=test_groups,
            )
        )
        results.append(run_backtest(test_strategy, db_path=db_path))

        train_start = _add_years(train_start, step_years)
        if test_end >= strategy.end_date:
            break

    return WalkForwardResult(windows=windows, results=results)


def _optimize_fold(
    strategy: StrategyDefinition,
    *,
    trials: int,
    objective: str,
    db_path: Path | None,
    seed: int = 42,
    weight_low: float = -2.0,
    weight_high: float = 2.0,
) -> StrategyDefinition:
    """Optimize factor weights on the train window with an in-memory study.

    Deliberately does NOT reuse optuna_runner.optimize_strategy: that writes
    report directories and a shared study DB, which per-fold optimization must
    not pollute. The suggestion/objective helpers are shared so the search
    space stays identical to the standalone optimizer.
    """
    import optuna

    from research.optimization.optuna_runner import (
        _objective_value,
        _strategy_with_params,
        _suggest_strategy,
    )

    def objective_fn(trial: optuna.Trial) -> float:
        candidate = _suggest_strategy(
            strategy, trial, weight_low=weight_low, weight_high=weight_high
        )
        result = run_backtest(candidate, db_path=db_path)
        value = _objective_value(result, objective.lower())
        return value if math.isfinite(value) else -1_000_000_000.0

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed),
    )
    study.optimize(objective_fn, n_trials=trials, gc_after_trial=True)
    return _strategy_with_params(strategy, study.best_params)


def _add_years(value: Date, years: int) -> Date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def _add_days(value: Date, days: int) -> Date:
    return Date.fromordinal(value.toordinal() + days)
