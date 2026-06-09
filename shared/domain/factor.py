"""Factor value domain models."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class FactorValue(BaseModel):
    stock_code: str
    date: date
    factor_name: str
    value: float
    disclosed_at: date | None
