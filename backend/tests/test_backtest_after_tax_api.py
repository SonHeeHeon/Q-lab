"""POST /api/backtest/run?after_tax=... 라우터 테스트 (T9).

backend.app.api.backtest.run_backtest / write_report 를 monkeypatch해 실제
(느린) 백테스트나 research/reports/ 파일시스템을 건드리지 않고, after_tax
배선만 검증한다: run_backtest 에 어떤 TaxModel 이 전달되는지, 응답 envelope
가 무엇을 담는지. 라우터 함수를 FastAPI 없이 직접 호출하는 방식은
test_api_ratings.py 와 동일 패턴이다.
"""

from __future__ import annotations

from datetime import date

import backend.app.api.backtest as backtest_api
from research.backtest.engine import EquityPoint, RunResult
from research.backtest.metrics import Metrics
from research.backtest.tax_kr import TaxModel
from shared.domain.strategy import StrategyDefinition


def _strategy(**overrides) -> StrategyDefinition:
    payload = dict(
        name="after_tax_api_test",
        description="after-tax api test",
        universe="ETF_KR",
        rebalance_freq="QUARTERLY",
        factors=[],
        filters=[],
        top_n=5,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    payload.update(overrides)
    return StrategyDefinition.model_validate(payload)


def _fake_result(strategy: StrategyDefinition) -> RunResult:
    metrics = Metrics(
        cagr=0.0,
        mdd=0.0,
        sharpe=0.0,
        sortino=0.0,
        win_rate=0.0,
        avg_holding_days=0.0,
        turnover=0.0,
        n_trades=0,
        total_tax_paid=0.0,
    )
    return RunResult(
        strategy_name=strategy.name,
        start_date=strategy.start_date,
        end_date=strategy.end_date,
        initial_nav=100_000_000.0,
        final_nav=100_000_000.0,
        equity_curve=[EquityPoint(date=strategy.start_date, nav=100_000_000.0)],
        trades=[],
        metrics=metrics,
        warnings=[],
    )


def _patch_run_and_write(monkeypatch, tmp_path, run_dir_name: str, captured: dict):
    def _fake_run_backtest(strategy, *, tax_model=None):
        captured["tax_model"] = tax_model
        return _fake_result(strategy)

    def _fake_write_report(result, strategy, *, tag=None, run_options=None):
        captured["run_options"] = run_options
        run_dir = tmp_path / run_dir_name
        run_dir.mkdir()
        return run_dir

    monkeypatch.setattr(backtest_api, "run_backtest", _fake_run_backtest)
    monkeypatch.setattr(backtest_api, "write_report", _fake_write_report)


async def test_after_tax_true_passes_tax_model_for_etf_kr(monkeypatch, tmp_path):
    captured: dict = {}
    _patch_run_and_write(monkeypatch, tmp_path, "run_etf", captured)

    strategy = _strategy(universe="ETF_KR")
    envelope = await backtest_api.run_backtest_api(strategy, after_tax=True)

    assert envelope.error is None
    assert isinstance(captured["tax_model"], TaxModel)
    assert captured["run_options"] == {"after_tax": True}
    assert envelope.data["after_tax"] is True
    assert "warnings" not in envelope.data


async def test_after_tax_true_nasdaq100_falls_back_pretax_with_warning(monkeypatch, tmp_path):
    captured: dict = {}
    _patch_run_and_write(monkeypatch, tmp_path, "run_us", captured)

    strategy = _strategy(universe="NASDAQ100")
    envelope = await backtest_api.run_backtest_api(strategy, after_tax=True)

    assert envelope.error is None
    assert captured["tax_model"] is None
    assert captured["run_options"] == {"after_tax": False}
    assert envelope.data["after_tax"] is False
    assert envelope.data["warnings"] == [
        "after_tax 미지원 유니버스(NASDAQ100) — 세전으로 실행"
    ]


async def test_after_tax_false_default_no_tax_model(monkeypatch, tmp_path):
    captured: dict = {}
    _patch_run_and_write(monkeypatch, tmp_path, "run_default", captured)

    strategy = _strategy(universe="ETF_KR")
    envelope = await backtest_api.run_backtest_api(strategy)

    assert envelope.error is None
    assert captured["tax_model"] is None
    assert captured["run_options"] == {"after_tax": False}
    assert envelope.data["after_tax"] is False
    assert "warnings" not in envelope.data
