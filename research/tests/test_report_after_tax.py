"""write_report() after-tax plumbing (T9).

Verifies write_report() persists ``run_options`` into params.yaml, trades.csv
carries the additive ``gains_tax`` column, and the leaderboard row gets an
``after_tax`` column — including migrating an older header-less
leaderboard.csv in place (read-modify-write) so old + new rows keep a
consistent header for csv.DictReader consumers.

REPORT_ROOT/RUNS_ROOT/LEADERBOARD_PATH are monkeypatched to a tmp_path so
this never touches the real research/reports/ tree.
"""

from __future__ import annotations

import csv
from datetime import date

import yaml

import research.scripts.run_backtest as run_backtest_script
from research.backtest.engine import EquityPoint, RunResult
from research.backtest.metrics import Metrics
from research.backtest.simulator import SimulatedTrade
from shared.domain.strategy import StrategyDefinition


def _strategy() -> StrategyDefinition:
    return StrategyDefinition.model_validate(
        {
            "name": "report_after_tax_test",
            "description": "report writer after-tax test",
            "universe": "ETF_KR",
            "rebalance_freq": "QUARTERLY",
            "factors": [],
            "filters": [],
            "top_n": 3,
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 3, 31),
        }
    )


def _result(strategy: StrategyDefinition) -> RunResult:
    trade = SimulatedTrade(
        date=date(2026, 2, 2),
        code="069500",
        side="SELL",
        qty=10,
        price=11000.0,
        notional=110000.0,
        commission=16.5,
        tax=0.0,
        slippage_bps=10.0,
        cash_flow=110000.0,
        gains_tax=1540.0,
    )
    metrics = Metrics(
        cagr=0.0,
        mdd=0.0,
        sharpe=0.0,
        sortino=0.0,
        win_rate=0.0,
        avg_holding_days=0.0,
        turnover=0.0,
        n_trades=1,
        total_tax_paid=1540.0,
    )
    return RunResult(
        strategy_name=strategy.name,
        start_date=strategy.start_date,
        end_date=strategy.end_date,
        initial_nav=100_000_000.0,
        final_nav=100_000_000.0,
        equity_curve=[EquityPoint(date=date(2026, 1, 2), nav=100_000_000.0)],
        trades=[trade],
        metrics=metrics,
        warnings=[],
    )


def _patch_report_paths(monkeypatch, tmp_path):
    # write_report() computes run_dir.relative_to(PROJECT_ROOT) (for the
    # leaderboard's run_dir column), so PROJECT_ROOT must also point at
    # tmp_path — otherwise a real tmp dir outside the repo raises ValueError.
    monkeypatch.setattr(run_backtest_script, "PROJECT_ROOT", tmp_path)
    report_root = tmp_path / "reports"
    runs_root = report_root / "runs"
    leaderboard_path = report_root / "leaderboard.csv"
    monkeypatch.setattr(run_backtest_script, "REPORT_ROOT", report_root)
    monkeypatch.setattr(run_backtest_script, "RUNS_ROOT", runs_root)
    monkeypatch.setattr(run_backtest_script, "LEADERBOARD_PATH", leaderboard_path)
    monkeypatch.setattr(run_backtest_script, "_git_commit", lambda: "deadbee")
    monkeypatch.setattr(run_backtest_script, "_research_schema_version", lambda: "test")
    return report_root, runs_root, leaderboard_path


def test_write_report_persists_run_options_and_gains_tax(monkeypatch, tmp_path):
    _, runs_root, leaderboard_path = _patch_report_paths(monkeypatch, tmp_path)
    strategy = _strategy()
    result = _result(strategy)

    run_dir = run_backtest_script.write_report(
        result, strategy, tag="after_tax_test", run_options={"after_tax": True}
    )

    assert run_dir.parent == runs_root

    with (run_dir / "params.yaml").open("r", encoding="utf-8") as file:
        params = yaml.safe_load(file)
    assert params["run_options"] == {"after_tax": True}

    with (run_dir / "trades.csv").open("r", encoding="utf-8", newline="") as file:
        header = next(csv.reader(file))
    assert "gains_tax" in header

    with (run_dir / "trades.csv").open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["gains_tax"] == "1540.0"

    with leaderboard_path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[-1]["after_tax"] == "True"


def test_write_report_without_run_options_omits_params_key(monkeypatch, tmp_path):
    _, _, leaderboard_path = _patch_report_paths(monkeypatch, tmp_path)
    strategy = _strategy()
    result = _result(strategy)

    run_dir = run_backtest_script.write_report(result, strategy, tag="no_options")

    with (run_dir / "params.yaml").open("r", encoding="utf-8") as file:
        params = yaml.safe_load(file)
    assert "run_options" not in params

    with leaderboard_path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[-1]["after_tax"] == "False"


def test_append_leaderboard_migrates_legacy_header(monkeypatch, tmp_path):
    _, _, leaderboard_path = _patch_report_paths(monkeypatch, tmp_path)
    leaderboard_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_fields = [
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
    with leaderboard_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=legacy_fields)
        writer.writeheader()
        writer.writerow(
            {
                "run_id": "legacy_run",
                "strategy": "legacy_strategy",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "final_nav": "100000000.000000",
                "cagr": "0.0000000000",
                "mdd": "0.0000000000",
                "sharpe": "0.0000000000",
                "win_rate": "0.0000000000",
                "n_trades": "0",
                "top_n": "3",
                "rebalance_freq": "QUARTERLY",
                "git_commit": "abc1234",
                "run_dir": "research/reports/runs/legacy_run",
            }
        )

    strategy = _strategy()
    result = _result(strategy)
    run_backtest_script.write_report(
        result, strategy, tag="after_migration", run_options={"after_tax": True}
    )

    with leaderboard_path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        assert reader.fieldnames is not None and "after_tax" in reader.fieldnames
        rows = list(reader)

    assert rows[0]["run_id"] == "legacy_run"
    assert rows[0]["after_tax"] == ""  # legacy row backfilled empty via restval
    assert rows[-1]["after_tax"] == "True"
