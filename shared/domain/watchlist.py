"""Watchlist domain models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WatchlistCategory(BaseModel):
    id: int
    name: str
    color: str
    sort_order: int


class WatchlistEntry(BaseModel):
    id: int
    stock_code: str
    category_id: int
    reason: str
    added_at: datetime
