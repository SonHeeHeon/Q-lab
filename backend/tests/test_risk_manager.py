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
from backend.app.services.kis.risk_manager import PortfolioRiskManager
from backend.app.services.kis.ws_client import QuoteTick
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
                    quantity=5,
                    avg_buy_price=Decimal("10000"),
                    current_price=Decimal("8900"),
                    evaluation_amount=Decimal("44500"),
                )
            ],
            summary=PortfolioSummary(account_type=account_type),
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
            kis_order_no="RISK-1",
            accepted_at=datetime.now(),
            raw={},
        )


@pytest.mark.asyncio
async def test_risk_manager_sells_once_when_stop_loss_is_hit(monkeypatch) -> None:
    sent_messages: list[str] = []

    async def fake_send_markdown(text: str):
        sent_messages.append(text)

    monkeypatch.setattr(
        "backend.app.services.kis.risk_manager.send_markdown",
        fake_send_markdown,
    )

    client = FakeKISClient()
    manager = PortfolioRiskManager(
        account_type=AccountType.PAPER,
        kis_client=client,
        stop_loss_pct=Decimal("-10"),
        is_mock=False,
    )
    await manager.refresh_positions()

    tick = QuoteTick(
        code="005930",
        price=8900,
        volume=100,
        change_pct=-2.5,
        timestamp=datetime.now(),
    )
    action = await manager.handle_tick(tick)
    duplicate = await manager.handle_tick(tick)

    assert action is not None
    assert action.stock_code == "005930"
    assert action.quantity == 5
    assert action.pnl_pct == Decimal("-11.00")
    assert duplicate is None
    assert len(client.orders) == 1
    assert client.orders[0].direction is TradeDirection.SELL
    assert client.orders[0].order_type is OrderType.MARKET
    assert "[긴급] 005930" in sent_messages[0]
