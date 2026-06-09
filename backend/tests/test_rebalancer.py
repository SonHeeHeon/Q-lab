from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from backend.app.schemas.portfolio import (
    OrderResponse,
    OrderType,
    PortfolioResponse,
    PortfolioSummary,
    PositionResponse,
)
from backend.app.services.kis.rebalancer import (
    build_rebalance_plan,
    execute_rebalance_plan,
)
from shared.domain.account import AccountType
from shared.domain.trade import TradeDirection


class FakeKISClient:
    def __init__(self) -> None:
        self.orders = []

    async def get_balance(self, account_type: AccountType) -> PortfolioResponse:
        return PortfolioResponse(
            account_type=account_type,
            positions=[
                PositionResponse(
                    stock_code="005930",
                    quantity=10,
                    avg_buy_price=Decimal("10000"),
                    current_price=Decimal("10000"),
                    evaluation_amount=Decimal("100000"),
                ),
                PositionResponse(
                    stock_code="000660",
                    quantity=10,
                    avg_buy_price=Decimal("20000"),
                    current_price=Decimal("20000"),
                    evaluation_amount=Decimal("200000"),
                ),
            ],
            summary=PortfolioSummary(
                account_type=account_type,
                total_evaluation_amount=Decimal("400000"),
                cash_amount=Decimal("100000"),
            ),
        )

    async def place_order(self, request):
        self.orders.append(request)
        return OrderResponse(
            account_type=request.account_type,
            stock_code=request.stock_code,
            direction=request.direction,
            quantity=request.quantity,
            order_type=request.order_type,
            price=request.price,
            kis_order_no=f"ORDER-{len(self.orders)}",
            accepted_at=datetime.now(),
            raw={},
        )


@pytest.mark.asyncio
async def test_rebalance_plan_sells_before_buys_and_mock_does_not_submit() -> None:
    client = FakeKISClient()
    plan = await build_rebalance_plan(
        account_type=AccountType.PAPER,
        target_weights={"005930": Decimal("0"), "000660": Decimal("1")},
        kis_client=client,
        min_trade_value=Decimal("1"),
        cash_buffer_pct=Decimal("0"),
    )

    assert [(order.direction, order.stock_code, order.quantity) for order in plan.orders] == [
        (TradeDirection.SELL, "005930", 10),
        (TradeDirection.BUY, "000660", 10),
    ]

    result = await execute_rebalance_plan(plan, kis_client=client, is_mock=True)
    assert result.is_mock is True
    assert result.attempted_orders == 2
    assert client.orders == []


@pytest.mark.asyncio
async def test_rebalance_live_mode_submits_market_orders() -> None:
    client = FakeKISClient()
    plan = await build_rebalance_plan(
        account_type=AccountType.PAPER,
        target_weights={"005930": Decimal("0"), "000660": Decimal("1")},
        kis_client=client,
        min_trade_value=Decimal("1"),
        cash_buffer_pct=Decimal("0"),
    )

    result = await execute_rebalance_plan(plan, kis_client=client, is_mock=False)

    assert result.is_mock is False
    assert [order.order_type for order in client.orders] == [OrderType.MARKET, OrderType.MARKET]
    assert [order.direction for order in client.orders] == [TradeDirection.SELL, TradeDirection.BUY]
    assert [response.kis_order_no for response in result.submitted_orders] == [
        "ORDER-1",
        "ORDER-2",
    ]
