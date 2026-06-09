"""Portfolio position domain models."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from shared.domain.account import AccountType


class Position(BaseModel):
    account_type: AccountType
    stock_code: str
    quantity: int
    avg_buy_price: Decimal
    current_price: Decimal | None
    unrealized_pl: Decimal | None
