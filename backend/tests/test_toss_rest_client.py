from __future__ import annotations

from decimal import Decimal

import pytest

from backend.app.schemas.portfolio import OrderRequest, OrderType
from backend.app.services.toss.rest_client import TossRestClient
from shared.domain.account import AccountType, BrokerType
from shared.domain.trade import TradeDirection


class FakeTossRestClient(TossRestClient):
    def __init__(self) -> None:
        super().__init__(client_id="client", client_secret="secret", account_seq=1)

    async def _request(self, method, path, **kwargs):  # noqa: ANN001
        if path == "/api/v1/accounts":
            return {
                "result": [
                    {
                        "accountNo": "12345678901",
                        "accountSeq": 1,
                        "accountType": "BROKERAGE",
                    }
                ]
            }
        if path == "/api/v1/holdings":
            return {
                "result": {
                    "totalPurchaseAmount": {"krw": "6500000", "usd": None},
                    "marketValue": {
                        "amount": {"krw": "7200000", "usd": None},
                        "amountAfterCost": {"krw": "7050000", "usd": None},
                    },
                    "profitLoss": {
                        "amount": {"krw": "700000", "usd": None},
                        "amountAfterCost": {"krw": "550000", "usd": None},
                        "rate": "0.1077",
                        "rateAfterCost": "0.0846",
                    },
                    "dailyProfitLoss": {
                        "amount": {"krw": "100000", "usd": None},
                        "rate": "0.0141",
                    },
                    "items": [
                        {
                            "symbol": "005930",
                            "name": "삼성전자",
                            "marketCountry": "KR",
                            "currency": "KRW",
                            "quantity": "100",
                            "lastPrice": "72000",
                            "averagePurchasePrice": "65000",
                            "marketValue": {
                                "purchaseAmount": "6500000",
                                "amount": "7200000",
                                "amountAfterCost": "7050000",
                            },
                            "profitLoss": {
                                "amount": "700000",
                                "amountAfterCost": "550000",
                                "rate": "0.1077",
                                "rateAfterCost": "0.0846",
                            },
                            "dailyProfitLoss": {"amount": "100000", "rate": "0.0141"},
                            "cost": {"commission": "14400", "tax": "135600"},
                        }
                    ],
                }
            }
        if path == "/api/v1/prices":
            return {
                "result": [
                    {
                        "symbol": "005930",
                        "timestamp": "2026-03-25T09:30:00.123+09:00",
                        "lastPrice": "72000",
                        "currency": "KRW",
                    }
                ]
            }
        raise AssertionError(path)


@pytest.mark.asyncio
async def test_toss_balance_maps_to_portfolio_schema() -> None:
    client = FakeTossRestClient()

    portfolio = await client.get_balance()

    assert portfolio.broker is BrokerType.TOSS
    assert portfolio.account_id == "1"
    assert portfolio.summary.total_evaluation_amount == Decimal("7200000")
    assert portfolio.summary.unrealized_pl_rate == Decimal("10.7700")
    assert portfolio.positions[0].stock_code == "005930"
    assert portfolio.positions[0].currency == "KRW"
    assert portfolio.positions[0].unrealized_pl_rate == Decimal("10.7700")


@pytest.mark.asyncio
async def test_toss_current_price_maps_to_broker_quote() -> None:
    client = FakeTossRestClient()

    quote = await client.get_current_price("005930")

    assert quote.broker is BrokerType.TOSS
    assert quote.symbol == "005930"
    assert quote.last_price == Decimal("72000")
    assert quote.currency == "KRW"


@pytest.mark.asyncio
async def test_toss_mock_order_never_calls_order_endpoint() -> None:
    client = FakeTossRestClient()
    request = OrderRequest(
        broker=BrokerType.TOSS,
        account_type=AccountType.REAL,
        account_id="1",
        stock_code="005930",
        direction=TradeDirection.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )

    response = await client.place_order(request)

    assert response.broker is BrokerType.TOSS
    assert response.broker_order_no is not None
    assert response.raw["mock"] is True
