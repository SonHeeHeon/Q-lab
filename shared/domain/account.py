"""KIS account domain models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, SecretStr


class AccountType(StrEnum):
    PAPER = "PAPER"
    REAL = "REAL"
    ISA = "ISA"
    DC = "DC"  # 퇴직연금 DC (OpenAPI 발급 문의 중 — env 비면 미연결)
    IRP = "IRP"  # 퇴직연금 IRP
    PENSION = "PENSION"  # 개인연금(연금저축)


class BrokerType(StrEnum):
    KIS = "KIS"
    TOSS = "TOSS"


class KISAccount(BaseModel):
    type: AccountType
    app_key: SecretStr
    app_secret: SecretStr
    account_no: str
    is_active: bool
