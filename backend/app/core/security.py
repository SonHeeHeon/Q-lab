"""
Module: backend.app.core.security

Role:
    Encryption helpers for at-rest secrets in `accounts` and `settings`
    tables. Also a stub for future auth (deferred to Phase 6+).

Planned:
    - Fernet symmetric encryption for KIS app_secret / API keys.
    - Key derivation: read `data/tokens/.salt` (auto-generated, 0600).
    - Helpers: `encrypt(plain: str) -> str`, `decrypt(token: str) -> str`.

Auth note:
    V1 has NO auth (single-user, localhost only). When exposing the
    backend to the home network, a future revision will add a static
    bearer token in env (`BACKEND_API_KEY`) and an HTTP middleware here.

Connected modules:
    - Used by: backend.app.api.settings (encrypt on write, decrypt on test)
               backend.app.services.kis.auth (decrypt before signing)
"""
