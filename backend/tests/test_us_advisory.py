"""US advisory sleeve — pure diff logic + (data-gated) live smoke."""

from __future__ import annotations

import sqlite3

import pytest

from backend.app.services.batch.us_advisory import build_advisory, generate_us_advisory
from shared.db.session import research_db_path


def test_build_advisory_buy_hold_sell():
    target = ["AAPL", "MSFT", "NVDA"]
    held = {"AAPL": 10, "TSLA": 3}  # AAPL in target(hold), TSLA not(sell)
    items = {i["ticker"]: i for i in build_advisory(target, held, strategy_name="us_value")}
    assert items["AAPL"]["action"] == "HOLD"
    assert items["MSFT"]["action"] == "BUY"
    assert items["NVDA"]["action"] == "BUY"
    assert items["TSLA"]["action"] == "SELL"
    # target weight = 1/3 for the 3 target names; ranks 1..3
    assert items["AAPL"]["target_weight"] == pytest.approx(0.3333, abs=1e-3)
    assert items["AAPL"]["rank"] == 1 and items["NVDA"]["rank"] == 3
    assert items["TSLA"]["rank"] is None


def test_build_advisory_empty_holdings_all_buy():
    items = build_advisory(["AAPL", "MSFT"], {}, strategy_name="us_momentum")
    assert all(i["action"] == "BUY" for i in items)


def test_build_advisory_universe_scopes_sell():
    # held has a KR code (005930) + a US ETF (QQQ) + an in-universe US stock (IBM).
    # Only IBM (in universe, dropped from target) should get SELL.
    universe = {"AAPL", "MSFT", "NVDA", "IBM"}
    held = {"005930": 100, "QQQ": 5, "IBM": 20}
    items = build_advisory(
        ["AAPL", "MSFT"], held, strategy_name="us_value", universe=universe
    )
    sells = {i["ticker"] for i in items if i["action"] == "SELL"}
    assert sells == {"IBM"}  # KR code + ETF excluded (not in US-stock sleeve)


def _has_us_data() -> bool:
    try:
        with sqlite3.connect(str(research_db_path)) as conn:
            if not conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='prices_daily_us'"
            ).fetchone():
                return False
            return conn.execute("SELECT COUNT(*) FROM prices_daily_us").fetchone()[0] > 0
    except Exception:
        return False


@pytest.mark.asyncio
async def test_generate_us_advisory_live_smoke():
    # 공개 기본 전략으로 검증 — 튜닝판(us_value 등)은 private/ 전용이라
    # 오픈소스 클론/CI에는 존재하지 않는다.
    if not _has_us_data():
        pytest.skip("no US price data in research.db")
    result = await generate_us_advisory("us_stock_v1", top_n=5, toss_client=None)
    assert result["strategy"] == "us_stock_v1"
    assert result["target_n"] == 5
    advisory = result["advisory"]
    # 5 target names; with no Toss configured they're all BUY suggestions.
    buys = [a for a in advisory if a["action"] == "BUY"]
    assert len(buys) == 5
    assert all(a["rank"] and 1 <= a["rank"] <= 5 for a in buys)
