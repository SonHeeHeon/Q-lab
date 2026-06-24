"""Portfolio API request and response schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, field_validator

from shared.domain.account import AccountType, BrokerType
from shared.domain.trade import TradeDirection

T = TypeVar("T")


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None


class ApiEnvelope(BaseModel, Generic[T]):
    data: T | None = None
    error: ApiError | None = None


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderRequest(BaseModel):
    broker: BrokerType = BrokerType.KIS
    account_type: AccountType = AccountType.PAPER
    account_id: str | None = None
    stock_code: str = Field(min_length=1, max_length=20)
    direction: TradeDirection
    quantity: int = Field(gt=0)
    order_type: OrderType = OrderType.LIMIT
    price: Decimal | None = Field(default=None, ge=0)
    exchange_id: str = "KRX"

    @field_validator("stock_code")
    @classmethod
    def normalize_stock_code(cls, value: str) -> str:
        return value.strip()

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: Decimal | None, info) -> Decimal | None:
        order_type = info.data.get("order_type")
        if order_type == OrderType.LIMIT and value is None:
            raise ValueError("price is required for LIMIT orders")
        return value


class PositionResponse(BaseModel):
    broker: BrokerType = BrokerType.KIS
    account_type: AccountType | None = None
    account_id: str | None = None
    stock_code: str
    name: str | None = None
    currency: str | None = None
    market_country: str | None = None
    quantity: int
    avg_buy_price: Decimal
    current_price: Decimal | None = None
    purchase_amount: Decimal | None = None
    evaluation_amount: Decimal | None = None
    unrealized_pl: Decimal | None = None
    unrealized_pl_rate: Decimal | None = None


class PortfolioSummary(BaseModel):
    broker: BrokerType = BrokerType.KIS
    account_type: AccountType | None = None
    account_id: str | None = None
    currency: str | None = "KRW"
    total_evaluation_amount: Decimal | None = None
    stock_evaluation_amount: Decimal | None = None
    purchase_amount: Decimal | None = None
    cash_amount: Decimal | None = None
    cash_krw: Decimal | None = None
    cash_usd: Decimal | None = None
    unrealized_pl: Decimal | None = None
    unrealized_pl_rate: Decimal | None = None


class PortfolioResponse(BaseModel):
    broker: BrokerType = BrokerType.KIS
    account_type: AccountType | None = None
    account_id: str | None = None
    positions: list[PositionResponse]
    summary: PortfolioSummary
    raw_output2: dict[str, object] | None = None


class OrderResponse(BaseModel):
    broker: BrokerType = BrokerType.KIS
    account_type: AccountType | None = None
    account_id: str | None = None
    stock_code: str
    direction: TradeDirection
    quantity: int
    order_type: OrderType
    price: Decimal | None = None
    kis_order_no: str | None = None
    broker_order_no: str | None = None
    kis_order_time: str | None = None
    accepted_at: datetime
    raw: dict[str, object]


class TradePersistResult(BaseModel):
    trade_id: int | None = None
    persisted: bool
    note: str


class OrderEnvelopeData(BaseModel):
    order: OrderResponse
    trade_persistence: TradePersistResult


class BrokerOrderSyncRequest(BaseModel):
    account_type: AccountType | None = None
    start_date: date | None = None
    end_date: date | None = None
    stock_code: str | None = Field(default=None, min_length=6, max_length=7)

    @field_validator("stock_code")
    @classmethod
    def normalize_optional_stock_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class BrokerOrderSyncAccountResult(BaseModel):
    account_type: AccountType
    start_date: date
    end_date: date
    seen: int
    imported: int
    updated: int
    skipped: int
    trade_ids: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class BrokerOrderSyncResponse(BaseModel):
    started_at: datetime
    finished_at: datetime
    results: list[BrokerOrderSyncAccountResult]


class AccountSummaryResponse(BaseModel):
    broker: BrokerType = BrokerType.KIS
    account_type: AccountType | None = None
    account_id: str | None = None
    currency: str | None = "KRW"
    total_value: Decimal
    cash_balance: Decimal
    cash_krw: Decimal | None = None
    cash_usd: Decimal | None = None
    total_pl: Decimal
    total_pl_pct: Decimal


class UnifiedPositionResponse(PositionResponse):
    account_type: AccountType | None = None
    stock_name: str | None = None


class UnifiedPortfolioResponse(BaseModel):
    as_of: datetime
    total_value: Decimal
    total_pl: Decimal
    total_pl_pct: Decimal
    fx_rate: Decimal | None = None
    fx_as_of: datetime | None = None
    accounts: list[AccountSummaryResponse]
    positions: list[UnifiedPositionResponse]
    errors: list[dict[str, object]] = Field(default_factory=list)


PortfolioEnvelope = ApiEnvelope[PortfolioResponse]
UnifiedPortfolioEnvelope = ApiEnvelope[UnifiedPortfolioResponse]
OrderEnvelope = ApiEnvelope[OrderEnvelopeData]
BrokerOrderSyncEnvelope = ApiEnvelope[BrokerOrderSyncResponse]
