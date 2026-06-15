from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.app.services.kis import market_snapshot
from backend.app.services.kis.market_snapshot import MarketSession, get_market_session


KST = ZoneInfo("Asia/Seoul")


def test_market_session_boundaries(monkeypatch) -> None:
    monkeypatch.setattr(
        market_snapshot,
        "_is_krx_business_day_cached",
        lambda _date_text: True,
    )
    assert get_market_session(datetime(2026, 6, 9, 7, 59, tzinfo=KST)) is MarketSession.CLOSED
    assert get_market_session(datetime(2026, 6, 9, 8, 0, tzinfo=KST)) is MarketSession.PRE_MARKET
    assert get_market_session(datetime(2026, 6, 9, 8, 50, tzinfo=KST)) is MarketSession.PRE_MARKET
    assert get_market_session(datetime(2026, 6, 9, 8, 51, tzinfo=KST)) is MarketSession.CLOSED
    assert get_market_session(datetime(2026, 6, 9, 9, 0, tzinfo=KST)) is MarketSession.REGULAR
    assert get_market_session(datetime(2026, 6, 9, 15, 29, tzinfo=KST)) is MarketSession.REGULAR
    assert get_market_session(datetime(2026, 6, 9, 15, 30, tzinfo=KST)) is MarketSession.AFTER_HOURS
    assert get_market_session(datetime(2026, 6, 9, 15, 31, tzinfo=KST)) is MarketSession.AFTER_HOURS
    assert get_market_session(datetime(2026, 6, 9, 20, 0, tzinfo=KST)) is MarketSession.AFTER_HOURS
    assert get_market_session(datetime(2026, 6, 9, 20, 1, tzinfo=KST)) is MarketSession.CLOSED


def test_market_session_weekend_is_closed() -> None:
    assert get_market_session(datetime(2026, 6, 13, 10, 0, tzinfo=KST)) is MarketSession.CLOSED
