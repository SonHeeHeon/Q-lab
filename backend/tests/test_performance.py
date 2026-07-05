"""Unit tests for the pure performance helpers (no DB / HTTP).

Mirrors the pure-function test style of ``test_api_portfolio.py``: exercise the
equity-curve reconstruction and backtest-curve loader with in-memory fixtures.
"""

from __future__ import annotations

from datetime import date

from backend.app.services.performance import backtest_curve
from backend.app.services.performance.reconstruct import (
    FilledTrade,
    build_equity_curve,
    make_close_lookup,
    to_simulated_trades,
    total_return,
)


def test_filled_trade_cash_flow_signs() -> None:
    buy = FilledTrade(date(2026, 1, 2), "005930", "BUY", 10, 100.0, fees=5.0, taxes=0.0)
    sell = FilledTrade(date(2026, 1, 3), "005930", "SELL", 10, 110.0, fees=5.0, taxes=2.0)
    assert buy.cash_flow == -1005.0  # -(100*10 + 5)
    assert buy.signed_qty == 10
    assert sell.cash_flow == 1093.0  # 110*10 - 5 - 2
    assert sell.signed_qty == -10


def test_make_close_lookup_forward_fills() -> None:
    lookup = make_close_lookup(
        [
            ("A", date(2026, 1, 2), 100.0),
            ("A", date(2026, 1, 6), 120.0),  # gap over 1/3-1/5
        ]
    )
    assert lookup("A", date(2026, 1, 1)) is None  # before first bar
    assert lookup("A", date(2026, 1, 2)) == 100.0
    assert lookup("A", date(2026, 1, 4)) == 100.0  # forward-filled
    assert lookup("A", date(2026, 1, 6)) == 120.0
    assert lookup("UNKNOWN", date(2026, 1, 6)) is None


def test_build_equity_curve_tracks_positions_and_cash() -> None:
    d1, d2 = date(2026, 1, 2), date(2026, 1, 3)
    trades = [FilledTrade(d1, "A", "BUY", 10, 100.0)]
    lookup = make_close_lookup([("A", d1, 100.0), ("A", d2, 110.0)])
    curve = build_equity_curve(trades, [d1, d2], lookup, initial_capital=1000.0)
    # Day1: cash 1000-1000=0, holdings 10*100=1000 -> 1000
    # Day2: cash 0, holdings 10*110=1100 -> 1100
    assert curve == [(d1, 1000.0), (d2, 1100.0)]
    assert round(total_return(curve), 6) == 0.1


def test_build_equity_curve_no_trades_is_flat_cash() -> None:
    d1, d2 = date(2026, 1, 2), date(2026, 1, 3)
    curve = build_equity_curve([], [d1, d2], make_close_lookup([]), initial_capital=500.0)
    assert curve == [(d1, 500.0), (d2, 500.0)]
    assert total_return(curve) == 0.0


def test_total_return_empty_curve() -> None:
    assert total_return([]) == 0.0


def test_to_simulated_trades_maps_fields() -> None:
    trades = [FilledTrade(date(2026, 1, 2), "A", "buy", 3, 200.0, fees=1.0, taxes=0.5)]
    sims = to_simulated_trades(trades)
    assert len(sims) == 1
    sim = sims[0]
    assert sim.code == "A"
    assert sim.side == "BUY"
    assert sim.qty == 3
    assert sim.notional == 600.0
    assert sim.commission == 1.0
    assert sim.tax == 0.5
    assert sim.cash_flow == -601.5  # -(200*3 + 1 + 0.5)


def test_read_equity_curve_parses_csv(tmp_path) -> None:
    csv_path = tmp_path / "equity_curve.csv"
    csv_path.write_text(
        "date,nav\n2026-01-02,100.0\n2026-01-03,101.5\nbad,row\n",
        encoding="utf-8",
    )
    curve = backtest_curve.read_equity_curve(csv_path)
    assert curve == [(date(2026, 1, 2), 100.0), (date(2026, 1, 3), 101.5)]


def test_read_equity_curve_missing_file(tmp_path) -> None:
    assert backtest_curve.read_equity_curve(tmp_path / "nope.csv") == []


def test_list_run_dirs_matches_strategy_slug(tmp_path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "20260101_120000_value_v1").mkdir()
    (runs / "20260609_214640_value_v1").mkdir()
    (runs / "20260101_120000_v1").mkdir()  # different strategy, must NOT match
    (runs / "not_a_run_dir").mkdir()
    monkeypatch.setattr(backtest_curve, "RUNS_ROOT", runs)

    dirs = backtest_curve.list_run_dirs_for_strategy("value_v1")
    names = [d.name for d in dirs]
    assert names == ["20260609_214640_value_v1", "20260101_120000_value_v1"]  # newest first


def test_load_latest_backtest_curve_reads_newest(tmp_path, monkeypatch) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    old = runs / "20260101_120000_value_v1"
    new = runs / "20260609_214640_value_v1"
    old.mkdir()
    new.mkdir()
    (old / "equity_curve.csv").write_text("date,nav\n2026-01-01,100.0\n", encoding="utf-8")
    (new / "equity_curve.csv").write_text("date,nav\n2026-06-09,150.0\n", encoding="utf-8")
    monkeypatch.setattr(backtest_curve, "RUNS_ROOT", runs)

    curve = backtest_curve.load_latest_backtest_curve("value_v1")
    assert curve == [(date(2026, 6, 9), 150.0)]
