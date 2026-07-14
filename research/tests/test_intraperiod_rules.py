"""Intra-period trade rules (Phase 4.2): stop/TP, band trim, score-exit swap.

All rules default OFF — the back-compat test pins that. Integration tests use
the patched-engine fixture pattern from test_regime_monthly.py (prices-only
DB + fixed scoring), YEARLY rebalance so only the rule under test trades
after the initial buy.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

import research.backtest.engine as eng
from research.backtest.engine import (
    _band_trim_target,
    _score_exit_swaps,
    _track_entry_prices,
)
from research.backtest.simulator import SimulatedTrade
from shared.domain.strategy import StrategyDefinition


# --- pure helpers -------------------------------------------------------------

def _trade(code: str, side: str, qty: int, price: float) -> SimulatedTrade:
    return SimulatedTrade(
        date=date(2026, 1, 2), code=code, side=side, qty=qty, price=price,
        notional=qty * price, commission=0.0, tax=0.0, slippage_bps=0.0,
        cash_flow=(qty * price) if side == "SELL" else -(qty * price),
    )


def test_entry_prices_blend_and_clear():
    entries: dict[str, float] = {}
    _track_entry_prices(entries, [_trade("A", "BUY", 10, 100.0)], {})
    assert entries["A"] == pytest.approx(100.0)
    # Second buy blends: (10*100 + 10*120) / 20 = 110
    _track_entry_prices(entries, [_trade("A", "BUY", 10, 120.0)], {"A": 10})
    assert entries["A"] == pytest.approx(110.0)
    # Partial sell keeps the average…
    _track_entry_prices(entries, [_trade("A", "SELL", 5, 130.0)], {"A": 20})
    assert entries["A"] == pytest.approx(110.0)
    # …full exit clears it.
    _track_entry_prices(entries, [_trade("A", "SELL", 15, 130.0)], {"A": 15})
    assert "A" not in entries


def test_band_trim_target_trims_only_breachers():
    positions = {"A": 10, "B": 30}
    prices = {"A": 100.0, "B": 100.0}
    nav = 4000.0  # A 25%, B 75%; base weight = 0.995/2 ≈ 49.75%
    target = _band_trim_target(
        positions, prices, nav=nav, exposure=1.0, threshold=1.4
    )
    assert target is not None
    assert target["A"] == 10  # within band → untouched
    assert target["B"] == int(0.4975 * 4000 / 100)  # trimmed to base weight (19)


def test_band_trim_none_within_band():
    positions = {"A": 10, "B": 11}
    prices = {"A": 100.0, "B": 100.0}
    assert _band_trim_target(
        positions, prices, nav=2100.0, exposure=1.0, threshold=1.4
    ) is None


def test_score_exit_swaps_percentile_and_bench():
    ranked = ["C", "D", "A", "E", "B"]  # best → worst; percentiles 1.0..0.0
    held = {"A", "B"}
    swaps = _score_exit_swaps(ranked, held, rank_below=0.4)
    # A pct=0.5 stays; B pct=0.0 exits → best non-held C replaces it.
    assert swaps == [("B", "C")]


def test_score_exit_skips_names_missing_from_ranking():
    swaps = _score_exit_swaps(["C", "D"], {"A"}, rank_below=0.9)
    assert swaps == []  # held A absent from ranking → data gap, no forced sale


# --- integration (patched engine) ----------------------------------------------

def _strategy(**overrides) -> StrategyDefinition:
    payload = dict(
        name="rules_test",
        description="intra-period rules",
        universe="KOSPI_ALL",
        rebalance_freq="YEARLY",
        factors=[],
        filters=[],
        top_n=2,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
    )
    payload.update(overrides)
    return StrategyDefinition.model_validate(payload)


def _weekdays(start: date, end: date) -> list[date]:
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


@pytest.fixture()
def patched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Two stocks; B rallies through February. Selection fixed to [A, B]."""
    db = tmp_path / "research.db"
    days = _weekdays(date(2026, 1, 2), date(2026, 3, 31))
    feb = date(2026, 2, 2)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT, close REAL, adj_close REAL)"
        )
        for d in days:
            price_b = 100.0 if d < feb else 300.0
            conn.execute(
                "INSERT INTO prices_daily VALUES ('000001', ?, 100.0, NULL)",
                (d.isoformat(),),
            )
            conn.execute(
                "INSERT INTO prices_daily VALUES ('000002', ?, ?, NULL)",
                (d.isoformat(), price_b),
            )

    monkeypatch.setattr(eng, "get_universe", lambda *a, **k: ["000001", "000002"])
    scored = pd.DataFrame(
        {"score": [2.0, 1.0]}, index=pd.Index(["000002", "000001"], name="code")
    )
    monkeypatch.setattr(eng, "score_stocks", lambda *a, **k: scored.copy())
    monkeypatch.setattr(eng, "apply_filters", lambda frame, *a, **k: frame)
    return db, days


def test_rules_off_no_intraperiod_trades(patched):
    db, days = patched
    result = eng.run_backtest(_strategy(), db_path=db)
    # Only the initial rebalance buys — nothing after day 0 (back-compat).
    assert all(t.date == days[0] for t in result.trades)
    assert not any("rule=" in w for w in result.warnings)


def test_take_profit_exits_winner(patched):
    db, _days = patched
    result = eng.run_backtest(_strategy(take_profit_pct=0.5), db_path=db)
    sells = [t for t in result.trades if t.side == "SELL"]
    assert sells and sells[0].code == "000002"
    assert sells[0].date == date(2026, 2, 2)  # first day at +~200%
    assert any("rule=TAKE_PROFIT 000002" in w for w in result.warnings)


def test_stop_loss_exits_loser(monkeypatch, patched):
    db, days = patched
    # Flip B into a -50% crash instead of a rally.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE prices_daily SET close=50.0 WHERE stock_code='000002' AND date>=?",
                     (date(2026, 2, 2).isoformat(),))
    result = eng.run_backtest(_strategy(stop_loss_pct=-0.10), db_path=db)
    sells = [t for t in result.trades if t.side == "SELL"]
    assert sells and sells[0].code == "000002"
    assert sells[0].date == date(2026, 2, 2)
    assert any("rule=STOP_LOSS 000002" in w for w in result.warnings)
    # A (flat) must not be stopped out.
    assert not any(t.code == "000001" and t.side == "SELL" for t in result.trades)


def test_band_trim_trims_drifted_winner_at_month_start(patched):
    db, _days = patched
    result = eng.run_backtest(_strategy(band_trim_threshold=1.3), db_path=db)
    sells = [t for t in result.trades if t.side == "SELL"]
    assert sells and sells[0].code == "000002"
    # B's rally lands exactly on the Feb month boundary → trim fires that day.
    assert sells[0].date == date(2026, 2, 2)
    bought = sum(t.qty for t in result.trades if t.code == "000002" and t.side == "BUY")
    sold = sum(t.qty for t in sells if t.code == "000002")
    assert 0 < sold < bought  # partial trim, not liquidation
    assert any("rule=BAND_TRIM" in w for w in result.warnings)


def test_score_exit_swap_at_month_start(monkeypatch, patched):
    db, _days = patched
    frames = {
        "initial": pd.DataFrame(
            {"score": [2.0, 1.0]},
            index=pd.Index(["000002", "000001"], name="code"),
        ),
        # Later: B collapses to the bottom; C is the new best non-held name.
        "later": pd.DataFrame(
            {"score": [3.0, 2.0, 0.1]},
            index=pd.Index(["000003", "000001", "000002"], name="code"),
        ),
    }
    calls = {"n": 0}

    def fake_scores(*a, **k):
        calls["n"] += 1
        return (frames["initial"] if calls["n"] == 1 else frames["later"]).copy()

    monkeypatch.setattr(eng, "score_stocks", fake_scores)
    with sqlite3.connect(db) as conn:  # price rows for the replacement
        for d in _weekdays(date(2026, 1, 2), date(2026, 3, 31)):
            conn.execute(
                "INSERT INTO prices_daily VALUES ('000003', ?, 200.0, NULL)",
                (d.isoformat(),),
            )
    result = eng.run_backtest(_strategy(replace_if_rank_below=0.4), db_path=db)
    assert any(
        t.side == "SELL" and t.code == "000002" and t.date == date(2026, 2, 2)
        for t in result.trades
    )
    assert any(
        t.side == "BUY" and t.code == "000003" and t.date == date(2026, 2, 2)
        for t in result.trades
    )
    assert any("rule=SCORE_EXIT 000002→000003" in w for w in result.warnings)


# --- logic-based trade reasons (Phase 4.4) -----------------------------------

def test_rebalance_reason_carries_rank_and_score(patched):
    db, _days = patched
    result = eng.run_backtest(_strategy(), db_path=db)
    buys = {t.code: t.reason for t in result.trades if t.side == "BUY"}
    # Selection is [000002 (score 2), 000001 (score 1)] → ranks 1 and 2.
    assert buys["000002"]["rule"] == "REBALANCE_IN"
    assert buys["000002"]["rank"] == 1 and buys["000002"]["score"] == 2.0
    assert buys["000001"]["rank"] == 2 and buys["000001"]["score"] == 1.0


def test_take_profit_reason(patched):
    db, _days = patched
    result = eng.run_backtest(_strategy(take_profit_pct=0.5), db_path=db)
    tp = next(t for t in result.trades if t.side == "SELL" and t.code == "000002")
    assert tp.reason["rule"] == "TAKE_PROFIT"
    assert tp.reason["return"] >= 0.5  # +~200% at the exit


def test_stop_loss_reason(monkeypatch, patched):
    db, _days = patched
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE prices_daily SET close=50.0 WHERE stock_code='000002' AND date>=?",
            (date(2026, 2, 2).isoformat(),),
        )
    result = eng.run_backtest(_strategy(stop_loss_pct=-0.10), db_path=db)
    sl = next(t for t in result.trades if t.side == "SELL" and t.code == "000002")
    assert sl.reason["rule"] == "STOP_LOSS"
    assert sl.reason["return"] <= -0.10


def test_band_trim_reason(patched):
    db, _days = patched
    result = eng.run_backtest(_strategy(band_trim_threshold=1.3), db_path=db)
    trim = next(
        t for t in result.trades
        if t.side == "SELL" and t.code == "000002" and t.date == date(2026, 2, 2)
    )
    assert trim.reason["rule"] == "BAND_TRIM"


def test_score_exit_reason_links_exit_and_replacement(monkeypatch, patched):
    db, _days = patched
    frames = {
        "initial": pd.DataFrame(
            {"score": [2.0, 1.0]}, index=pd.Index(["000002", "000001"], name="code")
        ),
        "later": pd.DataFrame(
            {"score": [3.0, 2.0, 0.1]},
            index=pd.Index(["000003", "000001", "000002"], name="code"),
        ),
    }
    calls = {"n": 0}

    def fake_scores(*a, **k):
        calls["n"] += 1
        return (frames["initial"] if calls["n"] == 1 else frames["later"]).copy()

    monkeypatch.setattr(eng, "score_stocks", fake_scores)
    with sqlite3.connect(db) as conn:
        for d in _weekdays(date(2026, 1, 2), date(2026, 3, 31)):
            conn.execute(
                "INSERT INTO prices_daily VALUES ('000003', ?, 200.0, NULL)",
                (d.isoformat(),),
            )
    result = eng.run_backtest(_strategy(replace_if_rank_below=0.4), db_path=db)
    exit_sell = next(
        t for t in result.trades if t.side == "SELL" and t.code == "000002"
        and t.date == date(2026, 2, 2)
    )
    repl_buy = next(
        t for t in result.trades if t.side == "BUY" and t.code == "000003"
        and t.date == date(2026, 2, 2)
    )
    assert exit_sell.reason == {"rule": "SCORE_EXIT", "replaced_by": "000003"}
    assert repl_buy.reason == {"rule": "SCORE_EXIT_REPLACE", "replaces": "000002"}
