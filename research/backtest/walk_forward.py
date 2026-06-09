"""Walk-forward validation for strategy robustness checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path

from research.backtest.engine import RunResult, run_backtest
from shared.domain.strategy import StrategyDefinition


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    train_start: Date
    train_end: Date
    test_start: Date
    test_end: Date


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
) -> WalkForwardResult:
    """Run rolling out-of-sample test windows across the strategy period."""

    if train_years <= 0 or test_years <= 0 or step_years <= 0:
        raise ValueError("train_years, test_years, and step_years must be positive.")

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

        test_strategy = strategy.model_copy(
            update={
                "name": f"{strategy.name}_wf_{test_start.isoformat()}",
                "start_date": test_start,
                "end_date": test_end,
            },
            deep=True,
        )
        windows.append(
            WalkForwardWindow(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        results.append(run_backtest(test_strategy, db_path=db_path))

        train_start = _add_years(train_start, step_years)
        if test_end >= strategy.end_date:
            break

    return WalkForwardResult(windows=windows, results=results)


def _add_years(value: Date, years: int) -> Date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def _add_days(value: Date, days: int) -> Date:
    return Date.fromordinal(value.toordinal() + days)
