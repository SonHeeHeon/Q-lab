"""Toss US 슬리브: 티커 스코핑·zfill 오염 방지 (순수 로직)."""
from __future__ import annotations

from backend.app.services.batch.account_proposals import scope_us_positions


def test_scope_us_positions_by_universe():
    positions = {"AAPL": 10, "SPY": 5, "TSLA": 3}
    stock_universe = {"AAPL", "TSLA", "MSFT"}
    etf_universe = {"SPY", "QQQ"}
    assert scope_us_positions(positions, stock_universe) == {"AAPL": 10, "TSLA": 3}
    assert scope_us_positions(positions, etf_universe) == {"SPY": 5}


def test_scope_us_positions_never_zfills():
    positions = {"AAPL": 1}
    scoped = scope_us_positions(positions, {"AAPL"})
    assert list(scoped) == ["AAPL"]  # "00AAPL" 오염 금지 (과거 버그 재발 방지)


def test_scope_us_positions_empty_universe():
    assert scope_us_positions({"AAPL": 1}, set()) == {}
