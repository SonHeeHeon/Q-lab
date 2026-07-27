"""write_portfolio_report persistence tests (P2).

Builds a small synthetic ``PortfolioResult`` (no real backtest) and writes it
via ``write_portfolio_report`` with PORTFOLIOS_ROOT/REPORT_ROOT/
PORTFOLIO_LEADERBOARD_PATH/PROJECT_ROOT monkeypatched to tmp_path — mirrors
the pattern in test_report_after_tax.py (PROJECT_ROOT must also point at
tmp_path since the leaderboard writer computes run_dir.relative_to(PROJECT_ROOT)).
"""

from __future__ import annotations

import csv
import json
from datetime import date

import pytest

import research.scripts.run_backtest as run_backtest_script
from research.backtest.metrics import Metrics
from research.backtest.portfolio import PortfolioResult


def _metrics(**overrides) -> Metrics:
    payload = dict(
        cagr=0.12,
        mdd=-0.2,
        sharpe=1.1,
        sortino=1.3,
        win_rate=0.6,
        avg_holding_days=30.0,
        turnover=1.5,
        n_trades=10,
        total_tax_paid=0.0,
    )
    payload.update(overrides)
    return Metrics(**payload)


def _portfolio_result() -> PortfolioResult:
    curve = [
        (date(2020, 1, 1), 100.0),
        (date(2020, 1, 2), 101.0),
        (date(2020, 1, 3), 102.5),
    ]
    sleeves = [
        {"strategy_name": "alpha", "weight": 0.6, "metrics": _metrics(cagr=0.15)},
        {"strategy_name": "beta", "weight": 0.4, "metrics": _metrics(cagr=0.05)},
    ]
    return PortfolioResult(
        combined_metrics=_metrics(),
        blended_curve=curve,
        sleeves=sleeves,
        weights=[0.6, 0.4],
        rebalance="QUARTERLY",
        start_date=curve[0][0],
        end_date=curve[-1][0],
    )


def _patch_report_paths(monkeypatch, tmp_path):
    # write_portfolio_report() computes run_dir.relative_to(PROJECT_ROOT) for
    # the leaderboard's run_dir column, so PROJECT_ROOT must also point at
    # tmp_path — otherwise a real tmp dir outside the repo raises ValueError
    # (same requirement as test_report_after_tax.py's _patch_report_paths).
    monkeypatch.setattr(run_backtest_script, "PROJECT_ROOT", tmp_path)
    report_root = tmp_path / "reports"
    portfolios_root = report_root / "portfolios"
    leaderboard_path = report_root / "portfolio_leaderboard.csv"
    monkeypatch.setattr(run_backtest_script, "REPORT_ROOT", report_root)
    monkeypatch.setattr(run_backtest_script, "PORTFOLIOS_ROOT", portfolios_root)
    monkeypatch.setattr(
        run_backtest_script, "PORTFOLIO_LEADERBOARD_PATH", leaderboard_path
    )
    return report_root, portfolios_root, leaderboard_path


def test_write_portfolio_report_writes_expected_files(monkeypatch, tmp_path):
    _, portfolios_root, leaderboard_path = _patch_report_paths(monkeypatch, tmp_path)
    result = _portfolio_result()

    run_dir = run_backtest_script.write_portfolio_report(
        result,
        weights_meta={
            "after_tax": True,
            "insample": {
                "weights": [0.7, 0.3],
                "objective": "calmar",
                "value": 1.5,
                "trials": 30,
            },
        },
    )

    assert run_dir.parent == portfolios_root
    assert run_dir.exists()

    combined = json.loads((run_dir / "combined_metrics.json").read_text(encoding="utf-8"))
    assert combined["cagr"] == pytest.approx(0.12)
    assert combined["mdd"] == pytest.approx(-0.2)

    with (run_dir / "blended_equity_curve.csv").open(
        "r", encoding="utf-8", newline=""
    ) as file:
        rows = list(csv.DictReader(file))
    assert [row["date"] for row in rows] == ["2020-01-01", "2020-01-02", "2020-01-03"]
    assert float(rows[-1]["nav"]) == pytest.approx(102.5)

    weights = json.loads((run_dir / "weights.json").read_text(encoding="utf-8"))
    assert weights["sleeves"] == [
        {"strategy_name": "alpha", "weight": 0.6},
        {"strategy_name": "beta", "weight": 0.4},
    ]
    assert weights["rebalance"] == "QUARTERLY"
    assert weights["after_tax"] is True
    assert "after_tax" not in weights["optimal"]
    assert weights["optimal"]["insample"]["objective"] == "calmar"

    sleeves = json.loads((run_dir / "sleeves.json").read_text(encoding="utf-8"))
    assert sleeves[0]["strategy_name"] == "alpha"
    assert sleeves[0]["weight"] == pytest.approx(0.6)
    assert sleeves[0]["metrics"]["cagr"] == pytest.approx(0.15)
    assert sleeves[1]["strategy_name"] == "beta"

    assert leaderboard_path.exists()
    with leaderboard_path.open("r", encoding="utf-8", newline="") as file:
        leaderboard_rows = list(csv.DictReader(file))
    assert len(leaderboard_rows) == 1
    row = leaderboard_rows[0]
    assert row["portfolio_id"] == run_dir.name
    assert row["sleeves"] == "alpha|beta"
    assert row["weights"] == "0.600000|0.400000"
    assert row["run_dir"] == str(run_dir.relative_to(tmp_path))


def test_write_portfolio_report_without_weights_meta_omits_optimal(monkeypatch, tmp_path):
    _patch_report_paths(monkeypatch, tmp_path)
    result = _portfolio_result()

    run_dir = run_backtest_script.write_portfolio_report(result)

    weights = json.loads((run_dir / "weights.json").read_text(encoding="utf-8"))
    assert weights["after_tax"] is False
    assert weights["optimal"] is None
