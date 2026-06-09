"""
Module: backend.tests.test_kis_auth

Role:
    Verify backend.app.services.kis.auth behavior:
      - Token cache hit (no network call).
      - Token cache near-expiry → refresh.
      - Concurrent refresh requests collapse to a single network call
        (asyncio.Lock guard).
      - approval_key obtained independently of access_token.
"""
