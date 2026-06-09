"""
Module: shared.utils.logger

Role:
    Centralized loguru configuration. Every module should import the
    configured `logger` from here rather than importing loguru directly,
    so log format and rotation policy stay consistent.

Configuration outline (to be implemented):
    - Console sink: colored, level from $LOG_LEVEL.
    - File sink:    rotating daily, 14-day retention, gzip after rotation.
    - Structured `extra` fields (account, code, tr_id) propagated.

Usage:
    from shared.utils.logger import logger
    logger.bind(account="PAPER", code="005930").info("subscribed")

Anti-pattern guard:
    NEVER log secrets (KIS app_secret, API keys, telegram tokens).
    SecretStr fields prevent printing by default; do not call .get_secret_value()
    in log calls.

Connected modules:
    - Imported by: virtually every backend/* and research/* module.
"""
