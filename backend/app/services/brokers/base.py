"""Common broker client protocol used by service APIs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from backend.app.schemas.portfolio import OrderRequest, OrderResponse, PortfolioResponse
from shared.domain.account import AccountType, BrokerType


@dataclass(frozen=True, slots=True)
class BrokerAccountRef:
    broker: BrokerType
    account_type: AccountType | None = None
    account_id: str | None = None


@dataclass(frozen=True, slots=True)
class BrokerQuote:
    broker: BrokerType
    symbol: str
    last_price: Decimal
    currency: str
    timestamp: str | None = None
    raw: dict[str, object] | None = None


class BaseBrokerClient(Protocol):
    broker: BrokerType

    async def get_balance(self, account: BrokerAccountRef) -> PortfolioResponse:
        """Return normalized holdings and account summary."""

    async def place_order(self, request: OrderRequest) -> OrderResponse:
        """Submit or mock-submit an order."""

    async def get_current_price(
        self,
        symbol: str,
        *,
        account: BrokerAccountRef | None = None,
    ) -> BrokerQuote:
        """Return one normalized current-price quote."""
