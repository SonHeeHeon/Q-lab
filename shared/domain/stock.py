"""Core stock and market domain models."""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, model_validator


class Stock(BaseModel):
    code: str
    name: str
    market: Literal["KOSPI", "KOSDAQ"]
    sector: str | None
    industry: str | None
    listed_at: date
    delisted_at: date | None
    is_delisted: bool = False

    @model_validator(mode="after")
    def derive_is_delisted(self) -> Self:
        self.is_delisted = self.delisted_at is not None
        return self
