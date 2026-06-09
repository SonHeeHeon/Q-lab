"""
Module: backend.app.core.deps

Role:
    FastAPI dependency-injection helpers. Endpoints declare these as
    `Depends(...)` to receive ready-to-use sessions and clients.

Planned dependencies:
    - get_service_session()  → AsyncSession on service.db
    - get_research_session() → AsyncSession on research.db
    - get_kis_account(account_type: AccountType) → KISAccount
    - get_kis_client(account_type) → KISClient
    - get_llm_client() → LLMClient
    - get_telegram() → TelegramClient

Pattern:
    Use async generators with `yield` for sessions so they are properly
    closed even on request error. KIS/LLM/Telegram clients are
    singletons held by the registry.

Connected modules:
    - shared.db.session     (session factories)
    - backend.app.services.kis.accounts (KISClientRegistry)
    - backend.app.services.llm.client
    - backend.app.services.notify.telegram
"""
