"""Investment principle domain models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class PrincipleCategory(StrEnum):
    ABSOLUTE = "ABSOLUTE"
    CRITERIA = "CRITERIA"
    FREE_NOTE = "FREE_NOTE"


class Principle(BaseModel):
    id: int
    title: str
    body: str
    category: PrincipleCategory
    is_editable: bool
    updated_at: datetime
