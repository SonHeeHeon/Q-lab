"""
Module: shared.utils.config

Role:
    pydantic-settings root. Loads `.env` and exposes a typed `Settings`
    object the rest of the app imports.

Planned fields (mirroring .env.example):
    KIS_PAPER_APP_KEY / SECRET / ACCOUNT_NO
    KIS_REAL_APP_KEY  / SECRET / ACCOUNT_NO
    KIS_ISA_APP_KEY   / SECRET / ACCOUNT_NO
    KIS_DEFAULT_ACCOUNT      : Literal["PAPER", "REAL", "ISA"]
    LLM_PROVIDER             : Literal["openai", "anthropic"]
    OPENAI_API_KEY           : SecretStr
    LLM_MODEL                : str
    LLM_DAILY_TOKEN_BUDGET   : int
    LLM_CACHE_TTL_HOURS      : int
    TELEGRAM_BOT_TOKEN       : SecretStr
    TELEGRAM_CHAT_ID         : str
    DART_API_KEY             : SecretStr
    SERVICE_DB_PATH          : Path
    RESEARCH_DB_PATH         : Path
    TOKEN_CACHE_DIR          : Path
    LLM_CACHE_DIR            : Path
    LOG_LEVEL                : str
    TZ                       : str

Usage:
    from shared.utils.config import settings
    print(settings.KIS_DEFAULT_ACCOUNT)

Backend extension:
    `backend.app.core.config` extends this with backend-only fields
    (CORS origins, etc.) using `Settings.model_copy` or subclassing.

Connected modules:
    - Imported by: shared.db.session, shared.utils.logger,
                   backend.app.core.config,
                   research.scripts.* CLIs
"""
