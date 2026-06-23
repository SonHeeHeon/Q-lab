"""KIS account domain models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, SecretStr


class AccountType(StrEnum):
    PAPER = "PAPER"
    REAL = "REAL"
    ISA = "ISA"


class BrokerType(StrEnum):
    KIS = "KIS"
    TOSS = "TOSS"


class KISAccount(BaseModel):
    type: AccountType
    app_key: SecretStr
    app_secret: SecretStr
    account_no: str
    is_active: bool
