"""Trade journal domain models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from shared.domain.trade import TradeDirection


class TradeJournalEntry(BaseModel):
    id: int
    trade_id: int
    direction: TradeDirection
    reason: str
    applied_principle_ids: list[int]
    post_review: str | None
    created_at: datetime
