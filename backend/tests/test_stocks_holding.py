"""Held-status live-position tests (Phase 4.5 과제1).

Covers the symbol/ticker matching and the fail-safe fallback path so a broker
timeout/exception never breaks stock detail — and so a stock held via Toss
(US LRCX or KR 005930) is reported as held even with an empty trades ledger.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

import backend.app.api.stocks as stocks
from backend.app.api.stocks import (
    HoldingInfo,
    _fetch_live_holding,
    _live_holding_info,
    _position_matches,
)
from backend.app.schemas.portfolio import PositionResponse
from shared.domain.account import AccountType, BrokerType


def _pos(stock_code: str, *, name: str = "", qty: int = 10) -> PositionResponse:
    return PositionResponse(
        broker=BrokerType.TOSS,
        account_type=AccountType.REAL,
        account_id="acc",
        stock_code=stock_code,
        name=name,
        currency="USD",
        market_country="US",
        quantity=qty,
        avg_buy_price=Decimal("0"),
        current_price=Decimal("0"),
        purchase_amount=Decimal("0"),
        evaluation_amount=Decimal("0"),
        unrealized_pl=Decimal("0"),
        unrealized_pl_rate=Decimal("0"),
    )


# --- _position_matches --------------------------------------------------------

def test_kr_matches_on_zero_padded_code():
    assert _position_matches(_pos("005930"), "005930", "KR", None)
    assert _position_matches(_pos("5930"), "005930", "KR", None)  # zfill both sides
    assert not _position_matches(_pos("005930"), "000660", "KR", None)


def test_us_matches_on_ticker_case_insensitive():
    assert _position_matches(_pos("lrcx"), "LRCX", "US", None)
    assert not _position_matches(_pos("AAPL"), "LRCX", "US", None)


def test_us_name_fallback_when_symbol_differs():
    # Toss returns a slightly different symbol but the same display name.
    assert _position_matches(_pos("LRCS", name="Lam Research"), "LRCX", "US", "Lam Research")


def test_empty_position_code_never_matches():
    assert not _position_matches(_pos(""), "LRCX", "US", None)


# --- fetch + fallback ---------------------------------------------------------

async def test_fetch_returns_holding_on_match(monkeypatch):
    async def fake_positions(_market):
        return [_pos("LRCX", qty=7)]

    monkeypatch.setattr(stocks, "_live_positions", fake_positions)
    result = await _fetch_live_holding("LRCX", "US", None)
    assert result == HoldingInfo(is_holding=True, quantity=7)


async def test_fetch_none_when_not_held(monkeypatch):
    async def fake_positions(_market):
        return [_pos("AAPL", qty=3)]

    monkeypatch.setattr(stocks, "_live_positions", fake_positions)
    assert await _fetch_live_holding("LRCX", "US", None) is None


async def test_live_holding_falls_back_on_broker_exception(monkeypatch):
    async def boom(_market):
        raise RuntimeError("broker down")

    monkeypatch.setattr(stocks, "_live_positions", boom)
    # Exception is swallowed → None so the caller keeps the trades result.
    assert await _live_holding_info("LRCX", "US", None) is None


async def test_live_holding_falls_back_on_timeout(monkeypatch):
    async def slow(_market):
        await asyncio.sleep(999)

    monkeypatch.setattr(stocks, "_live_positions", slow)
    monkeypatch.setattr(stocks, "_LIVE_HOLDING_TIMEOUT_SECONDS", 0.05)
    assert await _live_holding_info("LRCX", "US", None) is None


# --- TTL cache (avoids re-hitting Toss rate limit while browsing) -------------

async def test_live_positions_caches_within_ttl(monkeypatch):
    from types import SimpleNamespace

    stocks._POSITIONS_CACHE.clear()
    calls = {"n": 0}

    class _FakeToss:
        is_configured = True

        async def get_balance(self, _ref):
            calls["n"] += 1
            return SimpleNamespace(positions=[_pos("LRCX", qty=5)])

    async def fake_settings():
        return {}

    monkeypatch.setattr(stocks, "_settings_map_standalone", fake_settings)
    monkeypatch.setattr(
        stocks.TossRestClient, "from_settings_map", staticmethod(lambda rows: _FakeToss())
    )
    first = await stocks._live_positions("US")
    second = await stocks._live_positions("US")
    assert calls["n"] == 1  # second call served from the TTL cache
    assert len(first) == 1 and first == second
    stocks._POSITIONS_CACHE.clear()


async def test_live_positions_does_not_cache_total_failure(monkeypatch):
    stocks._POSITIONS_CACHE.clear()

    class _BoomToss:
        is_configured = True

        async def get_balance(self, _ref):
            raise RuntimeError("rate limited")

    async def fake_settings():
        return {}

    monkeypatch.setattr(stocks, "_settings_map_standalone", fake_settings)
    monkeypatch.setattr(
        stocks.TossRestClient, "from_settings_map", staticmethod(lambda rows: _BoomToss())
    )
    await stocks._live_positions("US")
    # An all-failed lookup must NOT be cached, or a transient rate-limit would
    # pin '미보유' for the whole TTL window.
    assert "US" not in stocks._POSITIONS_CACHE
    stocks._POSITIONS_CACHE.clear()
