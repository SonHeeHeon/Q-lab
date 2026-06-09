"""Trade execution domain models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from shared.domain.account import AccountType


class TradeDirection(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Trade(BaseModel):
    id: int
    account_type: AccountType
    stock_code: str
    direction: TradeDirection
    quantity: int
    price: Decimal
    executed_at: datetime
    kis_order_no: str | None
    status: str = "PENDING"
    submitted_at: datetime | None = None
    filled_quantity: int = 0
    filled_price: Decimal | None = None
    fees: Decimal = Decimal("0")
    taxes: Decimal = Decimal("0")
    filled_at: datetime | None = None
    canceled_at: datetime | None = None
    last_checked_at: datetime | None = None
