"""Broker client factory and KIS adapter."""

from __future__ import annotations

from collections.abc import Mapping

from backend.app.schemas.portfolio import OrderRequest, OrderResponse, PortfolioResponse
from backend.app.services.brokers.base import BrokerAccountRef, BrokerQuote
from backend.app.services.kis.rest_client import KISRestClient
from backend.app.services.toss.rest_client import TossRestClient
from shared.domain.account import AccountType, BrokerType


class KISBrokerClient:
    broker = BrokerType.KIS

    def __init__(self, client: KISRestClient | None = None) -> None:
        self._client = client or KISRestClient()

    async def get_balance(self, account: BrokerAccountRef) -> PortfolioResponse:
        if account.account_type is None:
            raise ValueError("KIS account_type is required.")
        return await self._client.get_balance(account.account_type)

    async def place_order(self, request: OrderRequest) -> OrderResponse:
        return await self._client.place_order(request)

    async def get_current_price(
        self,
        symbol: str,
        *,
        account: BrokerAccountRef | None = None,
    ) -> BrokerQuote:
        account_type = account.account_type if account and account.account_type else AccountType.PAPER
        quote = await self._client.get_current_price(account_type, symbol)
        return BrokerQuote(
            broker=BrokerType.KIS,
            symbol=quote.stock_code,
            last_price=quote.current_price,
            currency="KRW",
            timestamp=None,
            raw=quote.raw,
        )


def broker_client(
    broker: BrokerType,
    *,
    settings_rows: Mapping[str, str] | None = None,
) -> KISBrokerClient | TossRestClient:
    if broker is BrokerType.KIS:
        return KISBrokerClient()
    if broker is BrokerType.TOSS:
        return TossRestClient.from_settings_map(settings_rows or {})
    raise ValueError(f"Unsupported broker: {broker}")
