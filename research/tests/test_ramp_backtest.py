"""백테스트 분할 진입(ramp_in_months) — 첫 달 1/N 투입, None=기존 동작."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

import research.backtest.engine as eng
from shared.domain.strategy import StrategyDefinition


def _weekdays(start: date, end: date) -> list[date]:
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _strategy(**overrides) -> StrategyDefinition:
    payload = dict(
        name="ramp_test",
        description="ramp-in backtest test",
        universe="ETF_KR",
        rebalance_freq="MONTHLY",
        factors=[],
        filters=[],
        top_n=2,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
    )
    payload.update(overrides)
    return StrategyDefinition.model_validate(payload)


@pytest.fixture()
def flat_db(tmp_path: Path) -> Path:
    db = tmp_path / "research.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT,"
            " close REAL, adj_close REAL)"
        )
        for d in _weekdays(date(2026, 1, 2), date(2026, 3, 31)):
            for code in ("111111", "222222"):
                conn.execute(
                    "INSERT INTO prices_daily VALUES (?, ?, 100.0, NULL)",
                    (code, d.isoformat()),
                )
    return db


def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eng, "get_universe", lambda *a, **k: ["111111", "222222"])
    monkeypatch.setattr(eng, "apply_filters", lambda frame, *a, **k: frame)
    frame = pd.DataFrame(
        {"score": [2.0, 1.0]}, index=pd.Index(["111111", "222222"], name="code")
    )
    monkeypatch.setattr(eng, "score_stocks", lambda *a, **k: frame.copy())


def _month_buy_notional(result, month: int) -> float:
    return sum(
        t.notional for t in result.trades
        if t.side == "BUY" and t.date.month == month
    )


def test_ramp_first_month_invests_one_third(monkeypatch, flat_db):
    _patch(monkeypatch)
    baseline = eng.run_backtest(_strategy(), db_path=flat_db)
    _patch(monkeypatch)
    ramped = eng.run_backtest(_strategy(ramp_in_months=3), db_path=flat_db)

    base_m1 = _month_buy_notional(baseline, 1)
    ramp_m1 = _month_buy_notional(ramped, 1)
    assert base_m1 > 0
    # 첫 달은 기준 대비 ~1/3 투입 (정수 수량 라운딩 여유 5%)
    assert ramp_m1 == pytest.approx(base_m1 / 3, rel=0.05)
    # 3개월차(3월)까지 누적하면 기준과 동일 수준으로 수렴
    total_ramp = sum(_month_buy_notional(ramped, m) for m in (1, 2, 3))
    assert total_ramp == pytest.approx(base_m1, rel=0.05)


def test_ramp_none_matches_baseline(monkeypatch, flat_db):
    _patch(monkeypatch)
    a = eng.run_backtest(_strategy(), db_path=flat_db)
    _patch(monkeypatch)
    b = eng.run_backtest(_strategy(ramp_in_months=None), db_path=flat_db)
    assert a.final_nav == b.final_nav
    assert len(a.trades) == len(b.trades)
