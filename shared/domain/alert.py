"""Alert domain models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class AlertCondition(StrEnum):
    PRICE_GTE = "PRICE_GTE"
    PRICE_LTE = "PRICE_LTE"
    PCT_DROP = "PCT_DROP"
    PCT_RISE = "PCT_RISE"
    VOLUME_SPIKE = "VOLUME_SPIKE"


class Alert(BaseModel):
    id: int
    stock_code: str
    condition: AlertCondition
    threshold: float
    triggered_at: datetime | None
    post_mortem: str | None
    created_at: datetime
