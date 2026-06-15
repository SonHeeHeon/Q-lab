"""Optuna-based Bayesian optimization for strategy factor weights."""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import optuna
import yaml

from research.backtest.engine import RunResult, run_backtest
from shared.domain.strategy import FactorWeight, StrategyDefinition

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = PROJECT_ROOT / "research" / "reports"
OPTIMIZATION_ROOT = REPORT_ROOT / "optimization"
STUDY_DB_PATH = REPORT_ROOT / "optuna_studies.db"


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    study_name: str
    objective: str
    best_value: float
    best_params: dict[str, float]
    output_dir: Path


def optimize_strategy(
    strategy: StrategyDefinition,
    *,
    trials: int = 100,
    objective: str = "sharpe",
    study_name: str | None = None,
    storage_path: Path = STUDY_DB_PATH,
    weight_low: float = -2.0,
    weight_high: float = 2.0,
    seed: int | None = 42,
) -> OptimizationResult:
    """Optimize factor weights for one strategy without any LLM dependencies."""

    if trials <= 0:
        raise ValueError("trials must be positive.")
    selected_objective = objective.lower()
    output_dir = _new_output_dir(strategy.name)
    resolved_study_name = study_name or f"{strategy.name}_{selected_objective}"
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    trial_rows: list[dict[str, object]] = []

    def objective_fn(trial: optuna.Trial) -> float:
        candidate = _suggest_strategy(
            strategy,
            trial,
            weight_low=weight_low,
            weight_high=weight_high,
        )
        result = run_backtest(candidate)
        value = _objective_value(result, selected_objective)
        if not math.isfinite(value):
            value = -1_000_000_000.0
        trial.set_user_attr("final_nav", result.final_nav)
        trial.set_user_attr("cagr", result.metrics.cagr)
        trial.set_user_attr("mdd", result.metrics.mdd)
        trial.set_user_attr("sharpe", result.metrics.sharpe)
        trial.set_user_attr("sortino", result.metrics.sortino)
        trial.set_user_attr("win_rate", result.metrics.win_rate)
        trial.set_user_attr("n_trades", result.metrics.n_trades)
        trial_rows.append(_trial_row(trial, result, value))
        return value

    study = optuna.create_study(
        study_name=resolved_study_name,
        storage=f"sqlite:///{storage_path}",
        direction="maximize",
        load_if_exists=True,
        sampler=optuna.samplers.TPESampler(seed=seed),
    )
    study.optimize(objective_fn, n_trials=trials, gc_after_trial=True)

    _write_outputs(
        output_dir,
        strategy,
        study,
        trial_rows,
        selected_objective,
        seed=seed,
        storage_path=storage_path,
        weight_low=weight_low,
        weight_high=weight_high,
    )
    return OptimizationResult(
        study_name=study.study_name,
        objective=selected_objective,
        best_value=float(study.best_value),
        best_params={key: float(value) for key, value in study.best_params.items()},
        output_dir=output_dir,
    )


def load_strategy(path: Path) -> StrategyDefinition:
    with path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    return StrategyDefinition.model_validate(payload)


def _suggest_strategy(
    strategy: StrategyDefinition,
    trial: optuna.Trial,
    *,
    weight_low: float,
    weight_high: float,
) -> StrategyDefinition:
    factors: list[FactorWeight] = []
    for factor in strategy.factors:
        key = f"{factor.factor.lower()}_weight"
        suggested_weight = trial.suggest_float(key, weight_low, weight_high)
        factors.append(factor.model_copy(update={"weight": suggested_weight}))
    return strategy.model_copy(update={"factors": factors}, deep=True)


def _objective_value(result: RunResult, objective: str) -> float:
    if objective == "sharpe":
        return result.metrics.sharpe
    if objective == "cagr":
        return result.metrics.cagr
    if objective == "sortino":
        return result.metrics.sortino
    if objective == "final_nav":
        return result.final_nav
    if objective == "calmar":
        drawdown = abs(result.metrics.mdd)
        return result.metrics.cagr / drawdown if drawdown > 0 else result.metrics.cagr
    raise ValueError(f"Unsupported objective: {objective}")


def _trial_row(
    trial: optuna.Trial,
    result: RunResult,
    objective_value: float,
) -> dict[str, object]:
    row: dict[str, object] = {
        "trial": trial.number,
        "objective_value": objective_value,
        "final_nav": result.final_nav,
        "cagr": result.metrics.cagr,
        "mdd": result.metrics.mdd,
        "sharpe": result.metrics.sharpe,
        "sortino": result.metrics.sortino,
        "win_rate": result.metrics.win_rate,
        "n_trades": result.metrics.n_trades,
    }
    row.update(trial.params)
    return row


def _write_outputs(
    output_dir: Path,
    strategy: StrategyDefinition,
    study: optuna.Study,
    trial_rows: list[dict[str, object]],
    objective: str,
    *,
    seed: int | None,
    storage_path: Path,
    weight_low: float,
    weight_high: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    best_strategy = _strategy_with_params(strategy, study.best_params)

    with (output_dir / "best_strategy.yaml").open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            best_strategy.model_dump(mode="json"),
            file,
            sort_keys=False,
            allow_unicode=True,
        )
    summary = {
        "study_name": study.study_name,
        "objective": objective,
        "best_value": study.best_value,
        "best_params": study.best_params,
        "n_trials_total": len(study.trials),
        "n_trials_this_run": len(trial_rows),
        "seed": seed,
        "storage_path": str(storage_path),
        "strategy_name": strategy.name,
        "universe": strategy.universe,
        "start_date": strategy.start_date.isoformat(),
        "end_date": strategy.end_date.isoformat(),
        "rebalance_freq": strategy.rebalance_freq,
        "top_n": strategy.top_n,
        "weight_low": weight_low,
        "weight_high": weight_high,
    }
    with (output_dir / "summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")
    _write_trials_csv(output_dir / "trials.csv", trial_rows)


def _strategy_with_params(
    strategy: StrategyDefinition,
    params: dict[str, float],
) -> StrategyDefinition:
    factors: list[FactorWeight] = []
    for factor in strategy.factors:
        key = f"{factor.factor.lower()}_weight"
        factors.append(factor.model_copy(update={"weight": params.get(key, factor.weight)}))
    return strategy.model_copy(update={"factors": factors}, deep=True)


def _write_trials_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _new_output_dir(strategy_name: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OPTIMIZATION_ROOT / f"{timestamp}_{strategy_name}_optuna"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize strategy factor weights.")
    parser.add_argument("--strategy", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument(
        "--objective",
        choices=["sharpe", "cagr", "sortino", "final_nav", "calmar"],
        default="sharpe",
    )
    parser.add_argument("--study-name", default=None)
    parser.add_argument("--weight-low", type=float, default=-2.0)
    parser.add_argument("--weight-high", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    strategy = load_strategy(args.strategy)
    result = optimize_strategy(
        strategy,
        trials=args.trials,
        objective=args.objective,
        study_name=args.study_name,
        weight_low=args.weight_low,
        weight_high=args.weight_high,
        seed=args.seed,
    )
    print(f"[optuna] study={result.study_name}")
    print(f"[optuna] objective={result.objective} best={result.best_value:.6f}")
    print(f"[optuna] best_params={result.best_params}")
    print(f"[optuna] output={result.output_dir.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
