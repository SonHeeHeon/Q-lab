"""Multi-sleeve portfolio backtest: blend N strategy equity curves at fixed
weights, and search for optimal blend weights (in-sample + walk-forward OOS).

Reuses the single-strategy engine unchanged (each sleeve's ``StrategyDefinition``
runs through ``run_backtest`` exactly as it would standalone); this module only
combines the resulting equity curves and searches the weight simplex. No
look-ahead is introduced: weight optimization always operates on a TRAIN window
and is only ever evaluated out-of-sample by ``optimize_sleeve_weights_oos``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import optuna
import pandas as pd

from research.backtest.engine import EquityPoint, RunResult, run_backtest
from research.backtest.metrics import Metrics, compute_metrics
from research.backtest.tax_kr import default_tax_model_for_universe
from research.optimization.optuna_runner import _objective_value
from shared.domain.strategy import StrategyDefinition

RebalanceFreq = Literal["MONTHLY", "QUARTERLY", "YEARLY"]
_FREQ_CODES: dict[str, str] = {"MONTHLY": "M", "QUARTERLY": "Q", "YEARLY": "Y"}
DEFAULT_BASE_NAV = 100_000_000.0


def normalize_curve(
    equity_curve: list[EquityPoint] | list[tuple[Date, float]],
) -> pd.Series:
    """Index-normalize an equity curve to 1.0 at its first value.

    Tolerates both ``EquityPoint`` objects (engine's native output) and plain
    ``(date, nav)`` tuples, so callers can pass a ``RunResult.equity_curve``
    directly or a synthetic curve built for tests.
    """
    if not equity_curve:
        return pd.Series(dtype="float64")

    dates: list[Date] = []
    navs: list[float] = []
    for point in equity_curve:
        if isinstance(point, EquityPoint):
            dates.append(point.date)
            navs.append(point.nav)
        else:
            day, nav = point
            dates.append(day)
            navs.append(float(nav))

    series = pd.Series(navs, index=pd.to_datetime(dates), dtype="float64").sort_index()
    first_nav = float(series.iloc[0])
    if first_nav == 0.0:
        return series
    return series / first_nav


def _normalize_weights(weights: list[float]) -> list[float]:
    total = sum(weights)
    if total == 0:
        raise ValueError("weights must not sum to zero.")
    return [weight / total for weight in weights]


def blend_curves(
    curves: list[pd.Series],
    weights: list[float],
    *,
    rebalance: RebalanceFreq | None = "QUARTERLY",
    base_nav: float = DEFAULT_BASE_NAV,
) -> list[tuple[Date, float]]:
    """Blend normalized sleeve curves at ``weights`` into one NAV series.

    ``rebalance=None`` is a buy-and-hold blend: ``Σ wᵢ × normalizedᵢ`` computed
    directly on the aligned curves, so weights drift with relative sleeve
    performance. ``rebalance in {MONTHLY, QUARTERLY, YEARLY}`` resets to the
    target weights at every period boundary: within each period every sleeve's
    return is measured from that period's opening value, blended at the fixed
    weights, and period end-values are chained multiplicatively so the whole
    series compounds correctly across resets.
    """
    if not curves:
        raise ValueError("curves must not be empty.")
    if len(curves) != len(weights):
        raise ValueError("curves and weights must be the same length.")
    norm_weights = _normalize_weights(weights)

    aligned = (
        pd.concat({i: curve for i, curve in enumerate(curves)}, axis=1, join="inner")
        .dropna()
        .sort_index()
    )
    if aligned.empty:
        return []

    if rebalance is None:
        blended = aligned.mul(norm_weights, axis=1).sum(axis=1)
    else:
        if rebalance not in _FREQ_CODES:
            raise ValueError(f"Unsupported rebalance frequency: {rebalance}")
        periods = aligned.index.to_period(_FREQ_CODES[rebalance])
        carry = 1.0
        pieces: list[pd.Series] = []
        for _, group in aligned.groupby(periods, sort=True):
            start_values = group.iloc[0]
            period_returns = group.div(start_values, axis=1)
            weighted = period_returns.mul(norm_weights, axis=1).sum(axis=1)
            scaled = weighted * carry
            pieces.append(scaled)
            carry = float(scaled.iloc[-1])
        blended = pd.concat(pieces)

    return [(idx.date(), float(base_nav * value)) for idx, value in blended.items()]


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    combined_metrics: Metrics
    blended_curve: list[tuple[Date, float]]
    sleeves: list[dict]
    weights: list[float]
    rebalance: RebalanceFreq | None
    start_date: Date
    end_date: Date


def run_portfolio_backtest(
    sleeves: list[tuple[StrategyDefinition, float]],
    *,
    rebalance: RebalanceFreq | None = "QUARTERLY",
    db_path: Path | None = None,
    after_tax: bool = False,
) -> PortfolioResult:
    """Run each sleeve's backtest once, then blend the curves at ``weights``."""
    if not sleeves:
        raise ValueError("sleeves must not be empty.")

    results = [
        run_backtest(
            strategy,
            db_path=db_path,
            tax_model=(
                default_tax_model_for_universe(strategy.universe) if after_tax else None
            ),
        )
        for strategy, _ in sleeves
    ]
    norm_weights = _normalize_weights([weight for _, weight in sleeves])
    curves = [normalize_curve(result.equity_curve) for result in results]
    blended_curve = blend_curves(curves, norm_weights, rebalance=rebalance)
    combined_metrics = compute_metrics(blended_curve, [])

    sleeve_breakdown = [
        {"strategy_name": result.strategy_name, "weight": weight, "metrics": result.metrics}
        for result, weight in zip(results, norm_weights, strict=True)
    ]

    if blended_curve:
        start_date, end_date = blended_curve[0][0], blended_curve[-1][0]
    else:
        start_date = min(result.start_date for result in results)
        end_date = max(result.end_date for result in results)

    return PortfolioResult(
        combined_metrics=combined_metrics,
        blended_curve=blended_curve,
        sleeves=sleeve_breakdown,
        weights=norm_weights,
        rebalance=rebalance,
        start_date=start_date,
        end_date=end_date,
    )


def _objective_score(metrics: Metrics, final_nav: float, objective: str) -> float:
    """Reuse ``optuna_runner._objective_value`` against a blended curve.

    ``_objective_value`` only reads ``result.metrics`` and ``result.final_nav``
    off its argument, so a duck-typed ``SimpleNamespace`` (no strategy_name/
    equity_curve needed) satisfies it without a real ``RunResult``.
    """
    pseudo_result = SimpleNamespace(metrics=metrics, final_nav=final_nav)
    return _objective_value(pseudo_result, objective)


def optimize_sleeve_weights(
    strategies: list[StrategyDefinition],
    *,
    rebalance: RebalanceFreq | None = "QUARTERLY",
    objective: str = "calmar",
    trials: int = 200,
    db_path: Path | None = None,
    after_tax: bool = False,
) -> dict:
    """Optuna search over the sleeve weight simplex.

    Each strategy's backtest runs exactly once (cached curves); every trial
    only re-blends the cached curves and recomputes metrics, so the search is
    cheap even with hundreds of trials.
    """
    if not strategies:
        raise ValueError("strategies must not be empty.")
    if trials <= 0:
        raise ValueError("trials must be positive.")
    objective = objective.lower()

    results = [
        run_backtest(
            strategy,
            db_path=db_path,
            tax_model=(
                default_tax_model_for_universe(strategy.universe) if after_tax else None
            ),
        )
        for strategy in strategies
    ]
    curves = [normalize_curve(result.equity_curve) for result in results]
    n = len(strategies)

    def objective_fn(trial: optuna.Trial) -> float:
        raw_weights = [trial.suggest_float(f"w_{i}", 0.0, 1.0) for i in range(n)]
        if sum(raw_weights) <= 0:
            return -1_000_000_000.0
        norm_weights = _normalize_weights(raw_weights)
        blended = blend_curves(curves, norm_weights, rebalance=rebalance)
        metrics = compute_metrics(blended, [])
        final_nav = blended[-1][1] if blended else 0.0
        value = _objective_score(metrics, final_nav, objective)
        return value if math.isfinite(value) else -1_000_000_000.0

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective_fn, n_trials=trials, gc_after_trial=True)

    best_raw = [study.best_params[f"w_{i}"] for i in range(n)]
    best_weights = _normalize_weights(best_raw) if sum(best_raw) > 0 else [1.0 / n] * n

    return {
        "weights": best_weights,
        "objective": objective,
        "value": float(study.best_value),
        "trials": trials,
    }


def _add_years(value: Date, years: int) -> Date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def _add_days(value: Date, days: int) -> Date:
    return Date.fromordinal(value.toordinal() + days)


def optimize_sleeve_weights_oos(
    strategies: list[StrategyDefinition],
    *,
    train_years: int = 5,
    test_years: int = 1,
    rebalance: RebalanceFreq | None = "QUARTERLY",
    objective: str = "calmar",
    trials: int = 200,
    db_path: Path | None = None,
    after_tax: bool = False,
) -> dict:
    """Walk-forward OOS weight search across every sleeve.

    Deliberately does not reuse ``walk_forward.walk_forward`` — that module is
    single-strategy (it re-optimizes one strategy's factor weights per fold).
    This is a pragmatic rolling split applied uniformly to every sleeve's
    ``StrategyDefinition``: fold N trains on
    ``[overall_start + N*test_years, train_start + train_years]`` and tests on
    the immediately following ``test_years`` window (no overlap between test
    windows), mirroring the train/test boundary math in
    ``walk_forward._add_years``/``_add_days``. For each fold, weights are
    optimized in-sample on the TRAIN window (``optimize_sleeve_weights``) and
    then applied unchanged to the same strategies run on the TEST window.
    """
    if not strategies:
        raise ValueError("strategies must not be empty.")
    if train_years <= 0 or test_years <= 0:
        raise ValueError("train_years and test_years must be positive.")

    overall_start = min(strategy.start_date for strategy in strategies)
    overall_end = max(strategy.end_date for strategy in strategies)
    n = len(strategies)

    fold_weights: list[list[float]] = []
    fold_metrics: list[float] = []
    train_start = overall_start

    while True:
        train_end = _add_years(train_start, train_years)
        test_start = _add_days(train_end, 1)
        test_end = _add_years(test_start, test_years)
        if test_start > overall_end:
            break
        if test_end > overall_end:
            test_end = overall_end

        train_strategies = [
            strategy.model_copy(
                update={
                    "name": f"{strategy.name}_oos_train_{train_start.isoformat()}",
                    "start_date": train_start,
                    "end_date": train_end,
                },
                deep=True,
            )
            for strategy in strategies
        ]
        optimized = optimize_sleeve_weights(
            train_strategies,
            rebalance=rebalance,
            objective=objective,
            trials=trials,
            db_path=db_path,
            after_tax=after_tax,
        )
        weights = optimized["weights"]

        test_strategies = [
            strategy.model_copy(
                update={
                    "name": f"{strategy.name}_oos_test_{test_start.isoformat()}",
                    "start_date": test_start,
                    "end_date": test_end,
                },
                deep=True,
            )
            for strategy in strategies
        ]
        test_result = run_portfolio_backtest(
            list(zip(test_strategies, weights, strict=True)),
            rebalance=rebalance,
            db_path=db_path,
            after_tax=after_tax,
        )
        final_nav = test_result.blended_curve[-1][1] if test_result.blended_curve else 0.0
        oos_value = _objective_score(test_result.combined_metrics, final_nav, objective)

        fold_weights.append(weights)
        fold_metrics.append(oos_value if math.isfinite(oos_value) else 0.0)

        train_start = _add_years(train_start, test_years)
        if test_end >= overall_end:
            break

    if not fold_weights:
        return {"weights": [1.0 / n] * n, "oos_metric_mean": 0.0, "folds": 0}

    mean_weights = _normalize_weights(
        [sum(fold[i] for fold in fold_weights) / len(fold_weights) for i in range(n)]
    )
    return {
        "weights": mean_weights,
        "oos_metric_mean": float(sum(fold_metrics) / len(fold_metrics)),
        "folds": len(fold_weights),
    }
