"""POST /api/backtest/run-portfolio + GET /api/backtest/portfolios(/{id}) 테스트 (P2).

backend.app.api.backtest.load_strategy / run_portfolio_backtest /
optimize_sleeve_weights / optimize_sleeve_weights_oos / write_portfolio_report
를 monkeypatch해 실제 (느린) 백테스트나 research/reports/ 파일시스템을 건드리지
않는다. 라우터 함수를 FastAPI 없이 직접 호출하는 방식은 test_api_ratings.py /
test_backtest_after_tax_api.py 와 동일 패턴이다.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

import backend.app.api.backtest as backtest_api
from research.backtest.metrics import Metrics
from research.backtest.portfolio import PortfolioResult
from shared.domain.strategy import StrategyDefinition


def _strategy(name: str) -> StrategyDefinition:
    return StrategyDefinition.model_validate(
        {
            "name": name,
            "description": f"{name} sleeve",
            "universe": "KOSPI200",
            "rebalance_freq": "QUARTERLY",
            "factors": [],
            "filters": [],
            "top_n": 5,
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 12, 31),
        }
    )


def _metrics(**overrides) -> Metrics:
    payload = dict(
        cagr=0.1,
        mdd=-0.15,
        sharpe=1.2,
        sortino=1.4,
        win_rate=0.55,
        avg_holding_days=20.0,
        turnover=1.0,
        n_trades=5,
        total_tax_paid=0.0,
    )
    payload.update(overrides)
    return Metrics(**payload)


def _fake_portfolio_result() -> PortfolioResult:
    curve = [(date(2026, 1, 1), 100.0), (date(2026, 6, 30), 110.0)]
    sleeves = [
        {"strategy_name": "alpha", "weight": 0.6, "metrics": _metrics(cagr=0.12)},
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


def _patch_load_strategy(monkeypatch, known: dict[str, StrategyDefinition]):
    def _fake_load_strategy(name: str) -> StrategyDefinition:
        if name not in known:
            raise FileNotFoundError(name)
        return known[name]

    monkeypatch.setattr(backtest_api, "load_strategy", _fake_load_strategy)


def _patch_run_portfolio_backtest(monkeypatch, captured: dict):
    def _fake_run_portfolio_backtest(sleeves, *, rebalance="QUARTERLY", after_tax=False, **kwargs):
        captured["sleeves"] = sleeves
        captured["rebalance"] = rebalance
        captured["after_tax"] = after_tax
        return _fake_portfolio_result()

    monkeypatch.setattr(
        backtest_api, "run_portfolio_backtest", _fake_run_portfolio_backtest
    )


def _patch_write_portfolio_report(monkeypatch, tmp_path: Path, dir_name: str, captured: dict):
    def _fake_write_portfolio_report(result, *, tag=None, weights_meta=None):
        captured["weights_meta"] = weights_meta
        run_dir = tmp_path / dir_name
        run_dir.mkdir()
        return run_dir

    monkeypatch.setattr(
        backtest_api, "write_portfolio_report", _fake_write_portfolio_report
    )


# --- POST /api/backtest/run-portfolio ---------------------------------------------


async def test_run_portfolio_empty_sleeves_returns_400():
    request = backtest_api.RunPortfolioRequest(sleeves=[])

    response = await backtest_api.run_portfolio_backtest_api(request)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    body = json.loads(response.body)
    assert body["error"]["code"] == "EMPTY_SLEEVES"


async def test_run_portfolio_unknown_strategy_returns_400(monkeypatch):
    _patch_load_strategy(monkeypatch, {"alpha": _strategy("alpha")})
    request = backtest_api.RunPortfolioRequest(
        sleeves=[
            backtest_api.PortfolioSleeveRequest(strategy_name="alpha", weight=0.5),
            backtest_api.PortfolioSleeveRequest(strategy_name="ghost", weight=0.5),
        ]
    )

    response = await backtest_api.run_portfolio_backtest_api(request)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    body = json.loads(response.body)
    assert body["error"]["code"] == "UNKNOWN_STRATEGY"
    assert "ghost" in body["error"]["message"]


async def test_run_portfolio_basic_returns_documented_shape(monkeypatch, tmp_path):
    _patch_load_strategy(
        monkeypatch, {"alpha": _strategy("alpha"), "beta": _strategy("beta")}
    )
    run_captured: dict = {}
    write_captured: dict = {}
    _patch_run_portfolio_backtest(monkeypatch, run_captured)
    _patch_write_portfolio_report(monkeypatch, tmp_path, "run_basic", write_captured)

    request = backtest_api.RunPortfolioRequest(
        sleeves=[
            backtest_api.PortfolioSleeveRequest(strategy_name="alpha", weight=0.6),
            backtest_api.PortfolioSleeveRequest(strategy_name="beta", weight=0.4),
        ],
        rebalance="MONTHLY",
    )

    envelope = await backtest_api.run_portfolio_backtest_api(request, after_tax=True)

    assert envelope.error is None
    data = envelope.data
    assert data["portfolio_id"] == "run_basic"
    assert data["rebalance"] == "QUARTERLY"  # from the (fake) PortfolioResult
    assert data["after_tax"] is True
    assert data["weights"] == [0.6, 0.4]
    assert data["combined_metrics"]["cagr"] == 0.1
    assert data["sleeves"] == [
        {"strategy_name": "alpha", "weight": 0.6, "metrics": {**_metrics(cagr=0.12).model_dump(mode="json")}},
        {"strategy_name": "beta", "weight": 0.4, "metrics": {**_metrics(cagr=0.05).model_dump(mode="json")}},
    ]
    assert data["optimal"] == {}

    # Resolved sleeves + rebalance/after_tax were threaded through correctly.
    assert [s.name for s, _ in run_captured["sleeves"]] == ["alpha", "beta"]
    assert [w for _, w in run_captured["sleeves"]] == [0.6, 0.4]
    assert run_captured["rebalance"] == "MONTHLY"
    assert run_captured["after_tax"] is True
    assert write_captured["weights_meta"] == {"after_tax": True}


async def test_run_portfolio_optimize_adds_insample_only(monkeypatch, tmp_path):
    _patch_load_strategy(
        monkeypatch, {"alpha": _strategy("alpha"), "beta": _strategy("beta")}
    )
    _patch_run_portfolio_backtest(monkeypatch, {})
    write_captured: dict = {}
    _patch_write_portfolio_report(monkeypatch, tmp_path, "run_optimize", write_captured)

    insample_result = {"weights": [0.7, 0.3], "objective": "calmar", "value": 2.0, "trials": 100}
    optimize_captured: dict = {}

    def _fake_optimize_sleeve_weights(strategies, *, rebalance, trials, after_tax=False, **kwargs):
        optimize_captured["strategies"] = strategies
        optimize_captured["rebalance"] = rebalance
        optimize_captured["trials"] = trials
        optimize_captured["after_tax"] = after_tax
        return insample_result

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("optimize_sleeve_weights_oos must not run when oos=False")

    monkeypatch.setattr(
        backtest_api, "optimize_sleeve_weights", _fake_optimize_sleeve_weights
    )
    monkeypatch.setattr(
        backtest_api, "optimize_sleeve_weights_oos", _must_not_be_called
    )

    request = backtest_api.RunPortfolioRequest(
        sleeves=[
            backtest_api.PortfolioSleeveRequest(strategy_name="alpha", weight=0.5),
            backtest_api.PortfolioSleeveRequest(strategy_name="beta", weight=0.5),
        ],
        optimize=True,
    )

    envelope = await backtest_api.run_portfolio_backtest_api(request)

    assert envelope.error is None
    assert envelope.data["optimal"] == {"insample": insample_result}
    assert optimize_captured["trials"] == backtest_api.PORTFOLIO_INSAMPLE_TRIALS
    assert write_captured["weights_meta"] == {
        "after_tax": False,
        "insample": insample_result,
    }


async def test_run_portfolio_optimize_with_oos_adds_both(monkeypatch, tmp_path):
    _patch_load_strategy(monkeypatch, {"alpha": _strategy("alpha")})
    _patch_run_portfolio_backtest(monkeypatch, {})
    _patch_write_portfolio_report(monkeypatch, tmp_path, "run_oos", {})

    insample_result = {"weights": [1.0], "objective": "calmar", "value": 1.0, "trials": 100}
    oos_result = {"weights": [1.0], "oos_metric_mean": 0.8, "folds": 2}

    monkeypatch.setattr(
        backtest_api,
        "optimize_sleeve_weights",
        lambda strategies, *, rebalance, trials, after_tax=False, **kwargs: insample_result,
    )
    monkeypatch.setattr(
        backtest_api,
        "optimize_sleeve_weights_oos",
        lambda strategies, *, rebalance, trials, after_tax=False, **kwargs: oos_result,
    )

    request = backtest_api.RunPortfolioRequest(
        sleeves=[backtest_api.PortfolioSleeveRequest(strategy_name="alpha", weight=1.0)],
        optimize=True,
        oos=True,
    )

    envelope = await backtest_api.run_portfolio_backtest_api(request)

    assert envelope.data["optimal"] == {"insample": insample_result, "oos": oos_result}


# --- GET /api/backtest/portfolios(/{id}) -------------------------------------------


async def test_list_portfolio_backtests_empty_when_no_leaderboard(monkeypatch, tmp_path):
    monkeypatch.setattr(
        backtest_api, "PORTFOLIO_LEADERBOARD_PATH", tmp_path / "missing.csv"
    )

    envelope = await backtest_api.list_portfolio_backtests()

    assert envelope.error is None
    assert envelope.data == []


async def test_get_portfolio_backtest_round_trips_seeded_report_dir(monkeypatch, tmp_path):
    portfolios_root = tmp_path / "portfolios"
    portfolio_id = "20260727_120000_alpha_beta"
    run_dir = portfolios_root / portfolio_id
    run_dir.mkdir(parents=True)

    combined_metrics = _metrics().model_dump(mode="json")
    weights = {
        "sleeves": [{"strategy_name": "alpha", "weight": 0.6}],
        "rebalance": "QUARTERLY",
        "after_tax": False,
        "optimal": None,
    }
    sleeves = [{"strategy_name": "alpha", "weight": 0.6, "metrics": combined_metrics}]

    (run_dir / "combined_metrics.json").write_text(
        json.dumps(combined_metrics), encoding="utf-8"
    )
    (run_dir / "weights.json").write_text(json.dumps(weights), encoding="utf-8")
    (run_dir / "sleeves.json").write_text(json.dumps(sleeves), encoding="utf-8")
    with (run_dir / "blended_equity_curve.csv").open(
        "w", encoding="utf-8", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=["date", "nav"])
        writer.writeheader()
        writer.writerow({"date": "2026-01-01", "nav": "100.0"})

    monkeypatch.setattr(backtest_api, "PORTFOLIOS_ROOT", portfolios_root)

    envelope = await backtest_api.get_portfolio_backtest(portfolio_id)

    assert envelope.error is None
    data = envelope.data
    assert data["portfolio_id"] == portfolio_id
    assert data["combined_metrics"] == combined_metrics
    assert data["weights"] == weights
    assert data["sleeves"] == sleeves
    assert data["blended_curve"] == [{"date": "2026-01-01", "nav": "100.0"}]


async def test_get_portfolio_backtest_missing_returns_404(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_api, "PORTFOLIOS_ROOT", tmp_path / "portfolios")

    with pytest.raises(HTTPException) as exc_info:
        await backtest_api.get_portfolio_backtest("does_not_exist")

    assert exc_info.value.status_code == 404
