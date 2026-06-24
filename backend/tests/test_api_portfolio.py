from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.app.api.portfolio import _unified_response
from backend.app.schemas.portfolio import PortfolioResponse, PortfolioSummary, PositionResponse
from backend.app.services.market_data.fx import FxRate
from shared.domain.account import BrokerType


def test_unified_portfolio_keeps_us_positions_native_and_converts_totals() -> None:
    fx_rate = FxRate(
        base="USD",
        quote="KRW",
        rate=Decimal("1400"),
        mid_rate=Decimal("1398"),
        as_of=datetime(2026, 6, 25, 9, 30, tzinfo=ZoneInfo("Asia/Seoul")),
        change_type="UP",
    )
    portfolio = PortfolioResponse(
        broker=BrokerType.TOSS,
        account_id="1",
        positions=[
            PositionResponse(
                broker=BrokerType.TOSS,
                account_id="1",
                stock_code="AAPL",
                name="Apple Inc.",
                currency="USD",
                market_country="US",
                quantity=10,
                avg_buy_price=Decimal("100"),
                current_price=Decimal("110"),
                purchase_amount=Decimal("1000"),
                evaluation_amount=Decimal("1100"),
                unrealized_pl=Decimal("100"),
            )
        ],
        summary=PortfolioSummary(
            broker=BrokerType.TOSS,
            account_id="1",
            currency="KRW",
            cash_krw=Decimal("10000"),
            cash_usd=Decimal("20"),
        ),
    )

    response = _unified_response([portfolio], [], fx_rate)

    assert response.fx_rate == Decimal("1400")
    assert response.total_value == Decimal("1578000")
    assert response.total_pl == Decimal("140000")
    assert response.accounts[0].cash_krw == Decimal("10000")
    assert response.accounts[0].cash_usd == Decimal("20")
    assert response.positions[0].evaluation_amount == Decimal("1100")
    assert response.positions[0].currency == "USD"
