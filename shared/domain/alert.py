"""Alert domain models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class AlertCondition(StrEnum):
    PRICE_GTE = "PRICE_GTE"
    PRICE_LTE = "PRICE_LTE"
    PRICE_ABOVE = "PRICE_ABOVE"
    PRICE_BELOW = "PRICE_BELOW"
    PCT_DROP = "PCT_DROP"
    PCT_RISE = "PCT_RISE"
    PCT_CHANGE = "PCT_CHANGE"
    VOLUME_SPIKE = "VOLUME_SPIKE"


class AlertAction(StrEnum):
    NOTIFY = "NOTIFY"
    BUY = "BUY"
    SELL = "SELL"


class MarketCountry(StrEnum):
    KR = "KR"
    US = "US"


class Alert(BaseModel):
    id: int
    stock_code: str
    broker: str = "KIS"
    market_country: MarketCountry = MarketCountry.KR
    symbol: str | None = None
    condition: AlertCondition
    threshold: float
    action: AlertAction = AlertAction.NOTIFY
    order_quantity: int | None = None
    account_type: str | None = None
    account_id: str | None = None
    is_enabled: bool = True
    last_checked_at: datetime | None = None
    last_price: float | None = None
    last_error: str | None = None
    triggered_at: datetime | None
    post_mortem: str | None
    created_at: datetime
