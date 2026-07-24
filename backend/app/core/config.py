"""Backend settings loaded from `.env`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.domain.account import AccountType, BrokerType, KISAccount

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

    TOSS_API_BASE_URL: str = "https://openapi.tossinvest.com"
    TOSS_CLIENT_ID: str = ""
    TOSS_CLIENT_SECRET: SecretStr = SecretStr("")
    TOSS_ACCOUNT_SEQ: int | None = None
    TOSS_IS_MOCK: bool = True
    TOSS_HTTP_TIMEOUT_SECONDS: int = 10
    TOSS_SSL_VERIFY: bool = True
    TOSS_CA_BUNDLE_PATH: Path | None = None

    MARKET_SNAPSHOT_AUTOSTART: bool = True
    MARKET_SNAPSHOT_ACCOUNT_TYPE: AccountType = AccountType.PAPER
    MARKET_SNAPSHOT_INTERVAL_MINUTES: int = 5
    MARKET_SNAPSHOT_REQUEST_CONCURRENCY: int = 8
    MARKET_SNAPSHOT_REQUEST_INTERVAL_SECONDS: float = 0.35
    MARKET_SNAPSHOT_STALE_AFTER_MINUTES: int = 10
    MARKET_SESSION_PRE_MARKET_START: str = "08:00"
    MARKET_SESSION_PRE_MARKET_END: str = "08:50"
    MARKET_SESSION_REGULAR_START: str = "09:00"
    MARKET_SESSION_REGULAR_END: str = "15:30"
    MARKET_SESSION_AFTER_HOURS_START: str = "15:30"
    MARKET_SESSION_AFTER_HOURS_END: str = "20:00"
    ORDER_TRACKER_AUTOSTART: bool = True
    ORDER_TRACKER_POLL_INTERVAL_SECONDS: int = 30
    ORDER_TRACKER_ORDER_TIMEOUT_SECONDS: int = 300
    AUTOMATION_KILL_SWITCH: bool = False
    AUTOMATION_MAX_ORDER_VALUE: int = 5_000_000
    AUTOMATION_MAX_DAILY_LOSS_PCT: float = -5.0
    REBALANCER_IS_MOCK: bool = True
    REBALANCER_MIN_TRADE_VALUE: int = 50_000
    REBALANCER_CASH_BUFFER_PCT: float = 0.005
    RISK_MANAGER_AUTOSTART: bool = False
    RISK_MANAGER_IS_MOCK: bool = True
    RISK_MANAGER_ACCOUNT_TYPE: AccountType = AccountType.PAPER
    RISK_MANAGER_STOP_LOSS_PCT: float = -10.0
    RISK_MANAGER_POSITION_REFRESH_SECONDS: int = 60
    # 매도축 등급(sell_axis) 표시용 STOP_LOSS 임계치 — RISK_MANAGER_STOP_LOSS_PCT
    # 와 값은 같지만 리스크 매니저 자동 청산과는 독립적으로 관리한다.
    RATING_STOP_LOSS_PCT: float = -10.0
    ALERT_MONITOR_AUTOSTART: bool = False
    ALERT_MONITOR_INTERVAL_SECONDS: int = 60
    ALERT_ORDER_IS_MOCK: bool = True
    ALERT_DEFAULT_BROKER: BrokerType = BrokerType.KIS

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

    # Backend API 정적 토큰 인증(선택). 빈 문자열이면 인증 OFF —
    # 로컬 단일 사용자(localhost) 기존 동작을 그대로 유지한다.
    # 값이 설정되면 /health·docs 를 제외한 모든 요청에
    # `Authorization: Bearer <key>` (또는 `X-API-Key: <key>`) 헤더를 요구한다.
    # 이 값은 절대 로그에 남기지 않는다.
    BACKEND_API_KEY: str = ""
    # 콤마 구분 추가 허용 오리진(예: 폰 웹 클라이언트).
    # localhost/127.0.0.1 은 main.py 의 regex 로 항상 허용되므로 여기 넣지 않아도 된다.
    # 빈 문자열이면 추가 오리진 없음(기존 localhost 전용 동작 유지).
    CORS_ORIGINS: str = ""
    WS_HEARTBEAT_INTERVAL_S: int = 30
    BATCH_SCHEDULER_AUTOSTART: bool = False
    APSCHEDULER_TIMEZONE: str = "Asia/Seoul"
    DAILY_ANALYSIS_CRON: str = "30 16 * * MON-FRI"
    DAILY_REPORT_CRON: str = "45 16 * * MON-FRI"
    DATA_SYNC_CRON: str = "0 18 * * MON-FRI"
    # 배치 스케줄러(BATCH_SCHEDULER_AUTOSTART)가 꺼져 있던 기간 뒤에도 서버가
    # 켜지면 가격/지수 데이터가 최신으로 따라잡도록, 시작 시 1회 run_data_sync를
    # 백그라운드로 실행한다(멱등·증분이라 반복 실행해도 안전). false면 비활성화.
    DATA_SYNC_ON_STARTUP: bool = True
    # 시작 시 alembic 마이그레이션을 head로 자동 적용(멱등). 사용자가 수동으로
    # `alembic upgrade head`를 안 해도 새 테이블(order_proposals 등) 누락으로
    # 500이 나지 않도록. false면 비활성화.
    AUTO_MIGRATE_ON_STARTUP: bool = True
    BROKER_ORDER_SYNC_CRON: str = "10 16 * * MON-FRI"
    NAV_SNAPSHOT_CRON: str = "20 16 * * MON-FRI"
    # 승인형 반자동: 제안 생성(data_sync 18:00 이후) / 미승인 제안 만료(개장 전)
    PROPOSAL_CRON: str = "40 18 * * MON-FRI"
    PROPOSAL_EXPIRY_CRON: str = "30 8 * * MON-FRI"
    PROPOSAL_ACCOUNT_TYPE: AccountType = AccountType.PAPER
    BROKER_ORDER_SYNC_LOOKBACK_DAYS: int = 7
    BROKER_ORDER_SYNC_ACCOUNTS: str = "PAPER,REAL,ISA"
    DEFAULT_STRATEGY_NAME: str = "value_v1"

    @field_validator("TOSS_ACCOUNT_SEQ", mode="before")
    @classmethod
    def empty_toss_account_seq_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

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

    @property
    def toss_ca_bundle_path(self) -> Path | None:
        return self._optional_file_path(self.TOSS_CA_BUNDLE_PATH)

    @property
    def toss_credentials_configured(self) -> bool:
        return bool(self.TOSS_CLIENT_ID and self.TOSS_CLIENT_SECRET.get_secret_value())

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
    def cors_origins_list(self) -> list[str]:
        """추가 허용 CORS 오리진. 콤마 구분 문자열 또는 리스트 모두 허용한다."""
        raw = self.CORS_ORIGINS
        if isinstance(raw, (list, tuple)):
            values = [str(item).strip() for item in raw]
        else:
            values = [item.strip() for item in str(raw).split(",")]
        return [item for item in values if item]

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
