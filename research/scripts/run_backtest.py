"""CLI for running a single research backtest and writing report artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.backtest.engine import RunResult, run_backtest
from shared.db.session import research_db_path
from shared.domain.strategy import StrategyDefinition

REPORT_ROOT = PROJECT_ROOT / "research" / "reports"
RUNS_ROOT = REPORT_ROOT / "runs"
LEADERBOARD_PATH = REPORT_ROOT / "leaderboard.csv"


def main() -> None:
    args = _parse_args()
    strategy = _load_strategy(args.strategy)
    result = run_backtest(strategy, initial_nav=args.initial_nav)
    run_dir = write_report(result, strategy, tag=args.tag)
    print(_summary(result, run_dir))


def write_report(
    result: RunResult,
    strategy: StrategyDefinition,
    *,
    tag: str | None = None,
) -> Path:
    created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = _slug(tag or strategy.name)
    run_id = f"{created_at}_{suffix}"
    run_dir = RUNS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    git_commit = _git_commit()
    schema_version = _research_schema_version()

    _write_params(run_dir, strategy, git_commit, schema_version)
    _write_metrics(run_dir, result)
    _write_trades(run_dir, result)
    _write_equity_curve(run_dir, result)
    _write_log(run_dir, result, git_commit, schema_version)
    _append_leaderboard(run_id, run_dir, result, strategy, git_commit)
    return run_dir


def _load_strategy(path: Path) -> StrategyDefinition:
    with path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    return StrategyDefinition.model_validate(payload)


def _write_params(
    run_dir: Path,
    strategy: StrategyDefinition,
    git_commit: str,
    schema_version: str,
) -> None:
    payload = {
        "schema_version": {
            "research_db": schema_version,
        },
        "git_commit": git_commit,
        "strategy": strategy.model_dump(mode="json"),
    }
    with (run_dir / "params.yaml").open("w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, sort_keys=False, allow_unicode=True)


def _write_metrics(run_dir: Path, result: RunResult) -> None:
    payload = result.metrics.model_dump(mode="json")
    with (run_dir / "metrics.json").open("w", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        file.write("\n")


def _write_trades(run_dir: Path, result: RunResult) -> None:
    fields = [
        "date",
        "code",
        "side",
        "qty",
        "price",
        "notional",
        "commission",
        "tax",
        "slippage_bps",
        "cash_flow",
    ]
    with (run_dir / "trades.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for trade in result.trades:
            writer.writerow(trade.model_dump(mode="json"))


def _write_equity_curve(run_dir: Path, result: RunResult) -> None:
    with (run_dir / "equity_curve.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=["date", "nav"])
        writer.writeheader()
        for point in result.equity_curve:
            writer.writerow(point.model_dump(mode="json"))


def _write_log(
    run_dir: Path,
    result: RunResult,
    git_commit: str,
    schema_version: str,
) -> None:
    lines = [
        f"strategy={result.strategy_name}",
        f"period={result.start_date}..{result.end_date}",
        f"initial_nav={result.initial_nav:.2f}",
        f"final_nav={result.final_nav:.2f}",
        f"git_commit={git_commit}",
        f"research_db_schema={schema_version}",
        f"n_trades={len(result.trades)}",
        "warnings:",
    ]
    lines.extend(f"- {warning}" for warning in result.warnings)
    if not result.warnings:
        lines.append("- none")
    with (run_dir / "log.txt").open("w", encoding="utf-8") as file:
        file.write("\n".join(lines))
        file.write("\n")


def _append_leaderboard(
    run_id: str,
    run_dir: Path,
    result: RunResult,
    strategy: StrategyDefinition,
    git_commit: str,
) -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    fields = [
        "run_id",
        "strategy",
        "start_date",
        "end_date",
        "final_nav",
        "cagr",
        "mdd",
        "sharpe",
        "win_rate",
        "n_trades",
        "top_n",
        "rebalance_freq",
        "git_commit",
        "run_dir",
    ]
    row = {
        "run_id": run_id,
        "strategy": strategy.name,
        "start_date": result.start_date.isoformat(),
        "end_date": result.end_date.isoformat(),
        "final_nav": f"{result.final_nav:.6f}",
        "cagr": f"{result.metrics.cagr:.10f}",
        "mdd": f"{result.metrics.mdd:.10f}",
        "sharpe": f"{result.metrics.sharpe:.10f}",
        "win_rate": f"{result.metrics.win_rate:.10f}",
        "n_trades": result.metrics.n_trades,
        "top_n": strategy.top_n,
        "rebalance_freq": strategy.rebalance_freq,
        "git_commit": git_commit,
        "run_dir": str(run_dir.relative_to(PROJECT_ROOT)),
    }
    write_header = not LEADERBOARD_PATH.exists()
    with LEADERBOARD_PATH.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _research_schema_version() -> str:
    try:
        with sqlite3.connect(research_db_path) as conn:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error:
        return "unknown"
    return str(row[0]) if row else "unknown"


def _summary(result: RunResult, run_dir: Path) -> str:
    metrics = result.metrics
    return "\n".join(
        [
            f"[backtest] strategy={result.strategy_name}",
            f"[backtest] period={result.start_date}..{result.end_date}",
            f"[backtest] final_nav={result.final_nav:,.0f}",
            (
                "[backtest] "
                f"cagr={metrics.cagr:.2%} mdd={metrics.mdd:.2%} "
                f"sharpe={metrics.sharpe:.2f} win_rate={metrics.win_rate:.2%}"
            ),
            f"[backtest] trades={metrics.n_trades}",
            f"[backtest] report={run_dir.relative_to(PROJECT_ROOT)}",
        ]
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return slug.strip("._-") or "exp"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Q-Lab research backtest.")
    parser.add_argument(
        "--strategy",
        type=Path,
        required=True,
        help="Path to StrategyDefinition YAML.",
    )
    parser.add_argument("--tag", default=None, help="Optional run folder suffix.")
    parser.add_argument("--initial-nav", type=float, default=100_000_000.0)
    return parser.parse_args()


if __name__ == "__main__":
    main()
