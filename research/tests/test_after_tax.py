"""After-tax backtest mode (T8): TaxModel + engine capital-gains deduction.

Integration tests reuse the patched-engine fixture pattern from
test_regime_monthly.py / test_intraperiod_rules.py (prices-only DB + fixed
scoring), MONTHLY rebalance with top_n=1 so a single rotation forces a
full-exit SELL of the held code at a known realized gain.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

import research.backtest.engine as eng
from research.backtest.engine import _apply_capital_gains_tax
from research.backtest.metrics import compute_metrics
from research.backtest.simulator import SimulatedTrade
from research.backtest.tax_kr import TaxModel, default_tax_model_for_universe
from shared.domain.strategy import StrategyDefinition


# --- TaxModel unit tests -------------------------------------------------------

def test_gains_tax_for_taxable_etf_positive_gain():
    model = TaxModel()
    # 133690 = TIGER 미국나스닥100 (etf_taxable in kr_etf_tax_class.csv).
    assert model.gains_tax_for("133690", 1_000_000.0) == pytest.approx(154_000.0)


def test_gains_tax_for_negative_gain_is_zero():
    model = TaxModel()
    assert model.gains_tax_for("133690", -500_000.0) == 0.0


def test_gains_tax_for_domestic_equity_etf_is_zero():
    model = TaxModel()
    # 069500 = KODEX 200 (etf_domestic_equity -> 매매차익 비과세).
    assert model.gains_tax_for("069500", 1_000_000.0) == 0.0


def test_gains_tax_for_stock_code_is_zero():
    model = TaxModel()
    assert model.gains_tax_for("005930", 1_000_000.0) == 0.0


def test_gains_tax_for_unknown_ticker_is_zero():
    model = TaxModel()
    assert model.gains_tax_for("AAPL", 1_000_000.0) == 0.0


def test_default_tax_model_for_kr_universe():
    assert default_tax_model_for_universe("ETF_KR") is not None
    assert default_tax_model_for_universe("KOSPI200") is not None


def test_default_tax_model_for_us_universe_is_annual_model():
    # 2026-07-28: US 세후 지원 — 연간 손익통산 양도세 모델(상세는 test_tax_us.py).
    from research.backtest.tax_kr import USCapitalGainsTaxModel

    assert isinstance(default_tax_model_for_universe("NASDAQ100"), USCapitalGainsTaxModel)
    assert isinstance(default_tax_model_for_universe("ETF_US"), USCapitalGainsTaxModel)


# --- _apply_capital_gains_tax pure-helper tests --------------------------------

def _trade(code: str, side: str, qty: int, price: float) -> SimulatedTrade:
    return SimulatedTrade(
        date=date(2026, 1, 2), code=code, side=side, qty=qty, price=price,
        notional=qty * price, commission=0.0, tax=0.0, slippage_bps=0.0,
        cash_flow=(qty * price) if side == "SELL" else -(qty * price),
    )


def test_apply_capital_gains_tax_deducts_and_stamps_sell():
    model = TaxModel()
    entry_prices = {"133690": 10_000.0}
    sell = _trade("133690", "SELL", 100, 20_000.0)
    cash = _apply_capital_gains_tax(model, entry_prices, [sell], cash=1_000_000.0)
    expected_gain = (20_000.0 - 10_000.0) * 100
    expected_tax = model.etf_taxable_gains_rate * expected_gain
    assert sell.gains_tax == pytest.approx(expected_tax)
    assert cash == pytest.approx(1_000_000.0 - expected_tax)


def test_apply_capital_gains_tax_ignores_buys():
    model = TaxModel()
    buy = _trade("133690", "BUY", 100, 20_000.0)
    cash = _apply_capital_gains_tax(model, {}, [buy], cash=1_000_000.0)
    assert buy.gains_tax == 0.0
    assert cash == 1_000_000.0


def test_apply_capital_gains_tax_entry_unknown_is_zero_no_crash():
    """A SELL against a position seeded without a tracked entry price (e.g.
    never bought this run) must realize 0 gain rather than guessing, and
    must not raise."""
    model = TaxModel()
    sell = _trade("133690", "SELL", 100, 20_000.0)
    cash = _apply_capital_gains_tax(model, {}, [sell], cash=1_000_000.0)
    assert sell.gains_tax == 0.0
    assert cash == 1_000_000.0


# --- Metrics.total_tax_paid -----------------------------------------------------

def test_compute_metrics_total_tax_paid_sums_tax_and_gains_tax():
    trades = [
        _trade("133690", "SELL", 10, 200.0),
        _trade("069500", "SELL", 5, 100.0),
    ]
    trades[0].tax = 100.0
    trades[0].gains_tax = 50.0
    trades[1].tax = 20.0
    trades[1].gains_tax = 0.0
    metrics = compute_metrics(
        [(date(2026, 1, 2), 100.0), (date(2026, 1, 5), 101.0)], trades
    )
    assert metrics.total_tax_paid == pytest.approx(170.0)


def test_compute_metrics_tolerates_trade_without_gains_tax_attr():
    trade = _trade("133690", "SELL", 10, 200.0)
    trade.tax = 42.0
    del trade.gains_tax  # simulate a legacy trade object predating the field
    metrics = compute_metrics(
        [(date(2026, 1, 2), 100.0), (date(2026, 1, 5), 101.0)], [trade]
    )
    assert metrics.total_tax_paid == pytest.approx(42.0)


# --- Engine integration ---------------------------------------------------------

def _weekdays(start: date, end: date) -> list[date]:
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _strategy(**overrides) -> StrategyDefinition:
    payload = dict(
        name="after_tax_test",
        description="after-tax backtest test scenario",
        universe="ETF_KR",
        rebalance_freq="MONTHLY",
        factors=[],
        filters=[],
        top_n=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 27),
    )
    payload.update(overrides)
    return StrategyDefinition.model_validate(payload)


def _rotation_db(tmp_path: Path, held_code: str) -> Path:
    """``held_code`` is bought in Jan at 100 and rallies to 200 by Feb; a
    filler code "999999" stays flat the whole window and becomes the Feb
    pick once ``held_code`` drops out of the (monkeypatched) score frame —
    forcing a full-exit SELL of ``held_code`` at a known realized gain."""
    db = tmp_path / "research.db"
    days = _weekdays(date(2026, 1, 2), date(2026, 2, 27))
    feb = date(2026, 2, 2)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT, close REAL, adj_close REAL)"
        )
        for d in days:
            price = 100.0 if d < feb else 200.0
            conn.execute(
                "INSERT INTO prices_daily VALUES (?, ?, ?, NULL)",
                (held_code, d.isoformat(), price),
            )
            conn.execute(
                "INSERT INTO prices_daily VALUES ('999999', ?, 100.0, NULL)",
                (d.isoformat(),),
            )
    return db


def _patch_rotation(monkeypatch: pytest.MonkeyPatch, held_code: str) -> None:
    monkeypatch.setattr(eng, "get_universe", lambda *a, **k: [held_code, "999999"])
    monkeypatch.setattr(eng, "apply_filters", lambda frame, *a, **k: frame)
    frames = {
        "jan": pd.DataFrame(
            {"score": [2.0, 1.0]}, index=pd.Index([held_code, "999999"], name="code")
        ),
        "feb": pd.DataFrame({"score": [1.0]}, index=pd.Index(["999999"], name="code")),
    }
    calls = {"n": 0}

    def fake_scores(*a, **k):
        calls["n"] += 1
        return (frames["jan"] if calls["n"] == 1 else frames["feb"]).copy()

    monkeypatch.setattr(eng, "score_stocks", fake_scores)


def test_after_tax_taxable_etf_deducts_realized_gain(monkeypatch, tmp_path):
    held_code = "133690"  # etf_taxable
    db = _rotation_db(tmp_path, held_code)

    _patch_rotation(monkeypatch, held_code)
    pre = eng.run_backtest(_strategy(), db_path=db)

    _patch_rotation(monkeypatch, held_code)  # fresh call-counter for the 2nd run
    after = eng.run_backtest(_strategy(), db_path=db, tax_model=TaxModel())

    sell = next(t for t in after.trades if t.side == "SELL" and t.code == held_code)
    assert sell.gains_tax > 0
    assert after.final_nav == pytest.approx(pre.final_nav - sell.gains_tax, rel=1e-9)
    assert after.metrics.total_tax_paid == pytest.approx(
        sum(t.tax + t.gains_tax for t in after.trades)
    )


def test_after_tax_domestic_equity_etf_no_deduction(monkeypatch, tmp_path):
    held_code = "069500"  # etf_domestic_equity -> gains tax-free
    db = _rotation_db(tmp_path, held_code)

    _patch_rotation(monkeypatch, held_code)
    pre = eng.run_backtest(_strategy(), db_path=db)

    _patch_rotation(monkeypatch, held_code)
    after = eng.run_backtest(_strategy(), db_path=db, tax_model=TaxModel())

    assert after.final_nav == pytest.approx(pre.final_nav)
    assert all(t.gains_tax == 0.0 for t in after.trades)


def test_default_tax_model_none_matches_pretax_behavior(monkeypatch, tmp_path):
    """run_backtest with tax_model=None (the default) is the pre-tax path:
    every trade carries gains_tax == 0.0 and total_tax_paid is only sell tax."""
    held_code = "133690"
    db = _rotation_db(tmp_path, held_code)
    _patch_rotation(monkeypatch, held_code)

    result = eng.run_backtest(_strategy(), db_path=db)

    assert result.trades  # sanity: the rotation actually traded
    assert all(t.gains_tax == 0.0 for t in result.trades)
    assert result.metrics.total_tax_paid == pytest.approx(
        sum(t.tax for t in result.trades)
    )
