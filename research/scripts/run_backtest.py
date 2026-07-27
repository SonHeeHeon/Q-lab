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
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.backtest.engine import RunResult, run_backtest
from research.backtest.portfolio import PortfolioResult
from research.backtest.tax_kr import default_tax_model_for_universe
from shared.db.session import research_db_path
from shared.domain.strategy import StrategyDefinition

REPORT_ROOT = PROJECT_ROOT / "research" / "reports"
RUNS_ROOT = REPORT_ROOT / "runs"
LEADERBOARD_PATH = REPORT_ROOT / "leaderboard.csv"
PORTFOLIOS_ROOT = REPORT_ROOT / "portfolios"
PORTFOLIO_LEADERBOARD_PATH = REPORT_ROOT / "portfolio_leaderboard.csv"


def main() -> None:
    args = _parse_args()
    strategy = _load_strategy(args.strategy)
    tax_model = None
    run_options: dict[str, Any] | None = None
    if args.after_tax:
        tax_model = default_tax_model_for_universe(strategy.universe)
        if tax_model is None:
            print(
                f"[backtest] after_tax 미지원 유니버스({strategy.universe}) — 세전으로 실행"
            )
        run_options = {"after_tax": tax_model is not None}
    result = run_backtest(strategy, initial_nav=args.initial_nav, tax_model=tax_model)
    run_dir = write_report(result, strategy, tag=args.tag, run_options=run_options)
    print(_summary(result, run_dir))


def write_report(
    result: RunResult,
    strategy: StrategyDefinition,
    *,
    tag: str | None = None,
    run_options: dict[str, Any] | None = None,
) -> Path:
    created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = _slug(tag or strategy.name)
    run_id = f"{created_at}_{suffix}"
    run_dir = RUNS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    git_commit = _git_commit()
    schema_version = _research_schema_version()

    _write_params(run_dir, strategy, git_commit, schema_version, run_options=run_options)
    _write_metrics(run_dir, result)
    _write_trades(run_dir, result)
    _write_equity_curve(run_dir, result)
    _write_log(run_dir, result, git_commit, schema_version)
    _append_leaderboard(run_id, run_dir, result, strategy, git_commit, run_options=run_options)
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
    *,
    run_options: dict[str, Any] | None = None,
) -> None:
    payload = {
        "schema_version": {
            "research_db": schema_version,
        },
        "git_commit": git_commit,
        "strategy": strategy.model_dump(mode="json"),
    }
    if run_options:
        payload["run_options"] = run_options
    with (run_dir / "params.yaml").open("w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, sort_keys=False, allow_unicode=True)


def _write_metrics(run_dir: Path, result: RunResult) -> None:
    payload = result.metrics.model_dump(mode="json")
    with (run_dir / "metrics.json").open("w", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        file.write("\n")


def _write_trades(run_dir: Path, result: RunResult) -> None:
    # Authoritative machine-readable log — includes the structured logic reason.
    dumped = [trade.model_dump(mode="json") for trade in result.trades]
    with (run_dir / "trades.json").open("w", encoding="utf-8") as file:
        json.dump(dumped, file, ensure_ascii=False, indent=2)

    # Human-friendly CSV — reason flattened to a JSON string cell.
    fields = [
        "date",
        "code",
        "side",
        "qty",
        "price",
        "notional",
        "commission",
        "tax",
        "gains_tax",
        "slippage_bps",
        "cash_flow",
        "reason",
    ]
    with (run_dir / "trades.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for trade, row in zip(result.trades, dumped):
            flat = dict(row)
            flat["reason"] = json.dumps(trade.reason, ensure_ascii=False) if trade.reason else ""
            writer.writerow(flat)


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
    *,
    run_options: dict[str, Any] | None = None,
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
        "after_tax",
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
        "after_tax": bool((run_options or {}).get("after_tax", False)),
    }

    # Older leaderboard.csv files predate the after_tax column. If the header
    # doesn't have it yet, migrate in place (read-modify-write) so every row
    # keeps aligning 1:1 with the header for DictReader consumers (GET
    # /api/backtest/runs) — old rows get after_tax="" via restval.
    if LEADERBOARD_PATH.exists():
        with LEADERBOARD_PATH.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            existing_fieldnames = reader.fieldnames
            existing_rows = list(reader) if existing_fieldnames else []
        if existing_fieldnames and "after_tax" not in existing_fieldnames:
            with LEADERBOARD_PATH.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fields, restval="")
                writer.writeheader()
                for old_row in existing_rows:
                    writer.writerow(old_row)

    write_header = not LEADERBOARD_PATH.exists()
    with LEADERBOARD_PATH.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, restval="")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def write_portfolio_report(
    result: PortfolioResult,
    *,
    tag: str | None = None,
    weights_meta: dict[str, Any] | None = None,
) -> Path:
    """Persist a multi-sleeve ``PortfolioResult`` under ``PORTFOLIOS_ROOT``.

    Mirrors ``write_report``'s run_dir timestamp/slug convention exactly
    (same ``datetime.now()`` stamp + ``_slug`` helper) but writes the
    portfolio-shaped artifact set instead: combined metrics, the blended
    equity curve, sleeve weights (+ optional optimizer metadata), and a
    per-sleeve breakdown, plus a leaderboard row.
    """
    created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    sleeve_names = "_".join(sleeve["strategy_name"] for sleeve in result.sleeves)
    suffix = _slug(tag or sleeve_names)
    portfolio_id = f"{created_at}_{suffix}"
    run_dir = PORTFOLIOS_ROOT / portfolio_id
    run_dir.mkdir(parents=True, exist_ok=False)

    _write_portfolio_metrics(run_dir, result)
    _write_blended_equity_curve(run_dir, result)
    _write_portfolio_weights(run_dir, result, weights_meta=weights_meta)
    _write_portfolio_sleeves(run_dir, result)
    _append_portfolio_leaderboard(portfolio_id, run_dir, result)
    return run_dir


def _write_portfolio_metrics(run_dir: Path, result: PortfolioResult) -> None:
    payload = result.combined_metrics.model_dump(mode="json")
    with (run_dir / "combined_metrics.json").open("w", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        file.write("\n")


def _write_blended_equity_curve(run_dir: Path, result: PortfolioResult) -> None:
    with (run_dir / "blended_equity_curve.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=["date", "nav"])
        writer.writeheader()
        for day, nav in result.blended_curve:
            writer.writerow({"date": day.isoformat(), "nav": nav})


def _write_portfolio_weights(
    run_dir: Path,
    result: PortfolioResult,
    *,
    weights_meta: dict[str, Any] | None,
) -> None:
    # ``after_tax`` isn't part of PortfolioResult (the engine has no notion of
    # it at the blend layer) so callers fold it into weights_meta; it's pulled
    # out of a copy here so the caller's own dict (e.g. reused for an API
    # response's "optimal" field) is never mutated.
    meta = dict(weights_meta or {})
    after_tax = bool(meta.pop("after_tax", False))
    payload = {
        "sleeves": [
            {"strategy_name": sleeve["strategy_name"], "weight": sleeve["weight"]}
            for sleeve in result.sleeves
        ],
        "rebalance": result.rebalance,
        "after_tax": after_tax,
        "optimal": meta or None,
    }
    with (run_dir / "weights.json").open("w", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        file.write("\n")


def _write_portfolio_sleeves(run_dir: Path, result: PortfolioResult) -> None:
    payload = [
        {
            "strategy_name": sleeve["strategy_name"],
            "weight": sleeve["weight"],
            "metrics": sleeve["metrics"].model_dump(mode="json"),
        }
        for sleeve in result.sleeves
    ]
    with (run_dir / "sleeves.json").open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _append_portfolio_leaderboard(
    portfolio_id: str,
    run_dir: Path,
    result: PortfolioResult,
) -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    fields = ["portfolio_id", "sleeves", "weights", "cagr", "mdd", "sharpe", "run_dir"]
    row = {
        "portfolio_id": portfolio_id,
        "sleeves": "|".join(sleeve["strategy_name"] for sleeve in result.sleeves),
        "weights": "|".join(f"{weight:.6f}" for weight in result.weights),
        "cagr": f"{result.combined_metrics.cagr:.10f}",
        "mdd": f"{result.combined_metrics.mdd:.10f}",
        "sharpe": f"{result.combined_metrics.sharpe:.10f}",
        "run_dir": str(run_dir.relative_to(PROJECT_ROOT)),
    }
    write_header = not PORTFOLIO_LEADERBOARD_PATH.exists()
    with PORTFOLIO_LEADERBOARD_PATH.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, restval="")
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
    parser.add_argument(
        "--after-tax",
        action="store_true",
        help=(
            "Apply KR after-tax modeling (default TaxModel for the strategy's "
            "universe). Unsupported (US) universes fall back to a pre-tax run "
            "with a printed warning."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
