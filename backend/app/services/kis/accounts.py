"""KIS account registry and endpoint mapping."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.config import Settings, settings
from shared.domain.account import AccountType, KISAccount


@dataclass(frozen=True, slots=True)
class KISEndpoints:
    rest_base_url: str
    websocket_url: str


@dataclass(frozen=True, slots=True)
class KISAccountConfig:
    account: KISAccount
    endpoints: KISEndpoints

    @property
    def account_type(self) -> AccountType:
        return self.account.type


PAPER_ENDPOINTS = KISEndpoints(
    rest_base_url="https://openapivts.koreainvestment.com:29443",
    websocket_url="ws://ops.koreainvestment.com:31000",
)

LIVE_ENDPOINTS = KISEndpoints(
    rest_base_url="https://openapi.koreainvestment.com:9443",
    websocket_url="ws://ops.koreainvestment.com:21000",
)


def endpoints_for(account_type: AccountType) -> KISEndpoints:
    if account_type is AccountType.PAPER:
        return PAPER_ENDPOINTS
    if account_type in {AccountType.REAL, AccountType.ISA}:
        return LIVE_ENDPOINTS
    raise ValueError(f"Unsupported account type: {account_type!r}")


class KISAccountRegistry:
    """Read-only registry for configured KIS accounts and endpoints."""

    def __init__(self, app_settings: Settings = settings) -> None:
        self._settings = app_settings

    @property
    def active_account_type(self) -> AccountType:
        return self._settings.KIS_DEFAULT_ACCOUNT

    @property
    def active(self) -> KISAccountConfig:
        return self.get(self.active_account_type)

    def get_account(self, account_type: AccountType) -> KISAccount:
        return self._settings.kis_account(account_type)

    def get_endpoints(self, account_type: AccountType) -> KISEndpoints:
        return endpoints_for(account_type)

    def get(self, account_type: AccountType) -> KISAccountConfig:
        return KISAccountConfig(
            account=self.get_account(account_type),
            endpoints=self.get_endpoints(account_type),
        )

    def all(self) -> dict[AccountType, KISAccountConfig]:
        return {account_type: self.get(account_type) for account_type in AccountType}


account_registry = KISAccountRegistry()
