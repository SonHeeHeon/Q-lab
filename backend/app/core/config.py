"""Backend settings loaded from `.env`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.domain.account import AccountType, KISAccount

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


def _load_dotenv_into_process() -> None:
    """Expose `.env` values to libraries that read from `os.environ` directly."""

    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_dotenv_fallback()
        return

    load_dotenv(ENV_FILE, override=False)


def _load_dotenv_fallback() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


_load_dotenv_into_process()


class Settings(BaseSettings):
    """Application settings shared by backend services."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    KIS_PAPER_APP_KEY: SecretStr = SecretStr("")
    KIS_PAPER_APP_SECRET: SecretStr = SecretStr("")
    KIS_PAPER_ACCOUNT_NO: str = ""

    KIS_REAL_APP_KEY: SecretStr = SecretStr("")
    KIS_REAL_APP_SECRET: SecretStr = SecretStr("")
    KIS_REAL_ACCOUNT_NO: str = ""

    KIS_ISA_APP_KEY: SecretStr = SecretStr("")
    KIS_ISA_APP_SECRET: SecretStr = SecretStr("")
    KIS_ISA_ACCOUNT_NO: str = ""

    KIS_DEFAULT_ACCOUNT: AccountType = AccountType.PAPER
    KIS_TOKEN_SAFETY_BUFFER_SECONDS: int = 300
    KIS_ACCESS_TOKEN_TTL_SECONDS: int = 24 * 60 * 60
    KIS_APPROVAL_KEY_TTL_SECONDS: int = 23 * 60 * 60
    KIS_HTTP_TIMEOUT_SECONDS: int = 10
    KIS_SSL_VERIFY: bool = True
    KIS_CA_BUNDLE_PATH: Path | None = None
    KIS_WS_AUTOSTART: bool = True
    KIS_WS_DEFAULT_CODES: str = "005930"
    KIS_WS_RECONNECT_MAX_SECONDS: int = 60
    ORDER_TRACKER_AUTOSTART: bool = True
    ORDER_TRACKER_POLL_INTERVAL_SECONDS: int = 30
    ORDER_TRACKER_ORDER_TIMEOUT_SECONDS: int = 300
    REBALANCER_IS_MOCK: bool = True
    REBALANCER_MIN_TRADE_VALUE: int = 50_000
    REBALANCER_CASH_BUFFER_PCT: float = 0.005
    RISK_MANAGER_AUTOSTART: bool = False
    RISK_MANAGER_IS_MOCK: bool = True
    RISK_MANAGER_ACCOUNT_TYPE: AccountType = AccountType.PAPER
    RISK_MANAGER_STOP_LOSS_PCT: float = -10.0
    RISK_MANAGER_POSITION_REFRESH_SECONDS: int = 60

    KRX_ID: str = ""
    KRX_PW: SecretStr = SecretStr("")

    LLM_PROVIDER: Literal["openai", "anthropic"] = "openai"
    OPENAI_API_KEY: SecretStr = SecretStr("")
    LLM_MODEL: str = "gpt-4o"
    LLM_DAILY_TOKEN_BUDGET: int = 200_000
    LLM_CACHE_TTL_HOURS: int = 24

    TELEGRAM_BOT_TOKEN: SecretStr = SecretStr("")
    TELEGRAM_CHAT_ID: str = ""
    TELEGRAM_SSL_VERIFY: bool = True
    TELEGRAM_CA_BUNDLE_PATH: Path | None = None
    DART_API_KEY: SecretStr = SecretStr("")

    SERVICE_DB_PATH: Path = Path("data/service.db")
    RESEARCH_DB_PATH: Path = Path("data/research.db")
    TOKEN_CACHE_DIR: Path = Path("data/tokens")
    LLM_CACHE_DIR: Path = Path("data/cache")

    LOG_LEVEL: str = "INFO"
    LOG_DIR: Path = Path("logs/backend")
    LOG_BACKUP_DAYS: int = 14
    TZ: str = "Asia/Seoul"

    CORS_ORIGINS: list[str] = ["http://localhost", "http://127.0.0.1"]
    WS_HEARTBEAT_INTERVAL_S: int = 30
    BATCH_SCHEDULER_AUTOSTART: bool = False
    APSCHEDULER_TIMEZONE: str = "Asia/Seoul"
    DAILY_ANALYSIS_CRON: str = "30 16 * * MON-FRI"
    DAILY_REPORT_CRON: str = "45 16 * * MON-FRI"
    DATA_SYNC_CRON: str = "0 18 * * MON-FRI"
    BROKER_ORDER_SYNC_CRON: str = "10 16 * * MON-FRI"
    BROKER_ORDER_SYNC_LOOKBACK_DAYS: int = 7
    BROKER_ORDER_SYNC_ACCOUNTS: str = "PAPER,REAL,ISA"
    DEFAULT_STRATEGY_NAME: str = "value_v1"

    def resolve_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path

    @property
    def token_cache_dir(self) -> Path:
        return self.resolve_path(self.TOKEN_CACHE_DIR)

    @property
    def service_db_path(self) -> Path:
        return self.resolve_path(self.SERVICE_DB_PATH)

    @property
    def research_db_path(self) -> Path:
        return self.resolve_path(self.RESEARCH_DB_PATH)

    @property
    def log_dir(self) -> Path:
        return self.resolve_path(self.LOG_DIR)

    @property
    def kis_ca_bundle_path(self) -> Path | None:
        return self._optional_file_path(self.KIS_CA_BUNDLE_PATH)

    @property
    def telegram_ca_bundle_path(self) -> Path | None:
        return self._optional_file_path(self.TELEGRAM_CA_BUNDLE_PATH)

    def _optional_file_path(self, value: Path | None) -> Path | None:
        if value is None:
            return None
        raw_value = str(value).strip()
        if raw_value in {"", "."}:
            return None
        return self.resolve_path(Path(raw_value))

    @property
    def kis_ws_default_codes(self) -> list[str]:
        return [
            code.strip()
            for code in self.KIS_WS_DEFAULT_CODES.split(",")
            if code.strip()
        ]

    @property
    def krx_credentials_configured(self) -> bool:
        return bool(self.KRX_ID and self.KRX_PW.get_secret_value())

    @property
    def broker_order_sync_accounts(self) -> list[AccountType]:
        values = [
            value.strip().upper()
            for value in self.BROKER_ORDER_SYNC_ACCOUNTS.split(",")
            if value.strip()
        ]
        if not values:
            return list(AccountType)
        return [AccountType(value) for value in values]

    def kis_account(self, account_type: AccountType) -> KISAccount:
        if account_type is AccountType.PAPER:
            return KISAccount(
                type=AccountType.PAPER,
                app_key=self.KIS_PAPER_APP_KEY,
                app_secret=self.KIS_PAPER_APP_SECRET,
                account_no=self.KIS_PAPER_ACCOUNT_NO,
                is_active=bool(self.KIS_PAPER_APP_KEY.get_secret_value()),
            )
        if account_type is AccountType.REAL:
            return KISAccount(
                type=AccountType.REAL,
                app_key=self.KIS_REAL_APP_KEY,
                app_secret=self.KIS_REAL_APP_SECRET,
                account_no=self.KIS_REAL_ACCOUNT_NO,
                is_active=bool(self.KIS_REAL_APP_KEY.get_secret_value()),
            )
        if account_type is AccountType.ISA:
            return KISAccount(
                type=AccountType.ISA,
                app_key=self.KIS_ISA_APP_KEY,
                app_secret=self.KIS_ISA_APP_SECRET,
                account_no=self.KIS_ISA_ACCOUNT_NO,
                is_active=bool(self.KIS_ISA_APP_KEY.get_secret_value()),
            )

        raise ValueError(f"Unsupported account type: {account_type!r}")


settings = Settings()
