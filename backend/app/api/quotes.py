"""Current quote REST API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.market_data.quotes import fetch_current_quotes
from shared.domain.account import AccountType, BrokerType

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


class CurrentQuoteResponse(BaseModel):
    broker: BrokerType
    symbol: str
    price: Decimal
    currency: str
    timestamp: datetime | str | None = None
    change_pct: Decimal | None = None
    volume: int | None = None


class CurrentQuotesResponse(BaseModel):
    broker: BrokerType
    account_type: AccountType | None = None
    account_id: str | None = None
    quotes: list[CurrentQuoteResponse]
    errors: dict[str, str]


@router.get("/current", response_model=ApiEnvelope[CurrentQuotesResponse])
async def get_current_quotes(
    broker: BrokerType = Query(default=BrokerType.KIS),
    symbols: str = Query(min_length=1),
    account_type: AccountType = Query(default=AccountType.PAPER),
    account_id: str | None = Query(default=None),
) -> ApiEnvelope[CurrentQuotesResponse]:
    symbol_list = [
        symbol.strip()
        for symbol in symbols.split(",")
        if symbol.strip()
    ]
    result = await fetch_current_quotes(
        broker=broker,
        symbols=symbol_list,
        account_type=account_type,
        account_id=account_id,
    )
    return ApiEnvelope(
        data=CurrentQuotesResponse(
            broker=broker,
            account_type=account_type if broker is BrokerType.KIS else None,
            account_id=account_id,
            quotes=[
                CurrentQuoteResponse(
                    broker=quote.broker,
                    symbol=quote.symbol,
                    price=quote.price,
                    currency=quote.currency,
                    timestamp=quote.timestamp,
                    change_pct=quote.change_pct,
                    volume=quote.volume,
                )
                for quote in result.quotes
            ],
            errors=result.errors,
        ),
        error=None,
    )
