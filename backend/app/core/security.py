"""
Module: backend.app.core.security

Role:
    HTTP authentication for the backend API. Provides an *optional* static
    bearer-token gate so the service can be safely exposed beyond localhost
    (e.g. to the user's phone on the home network) without breaking the
    original single-user / localhost workflow.

Auth design (backward compatible by default):
    - Controlled entirely by `settings.BACKEND_API_KEY`.
    - Empty (the default) -> auth DISABLED. Every request passes untouched,
      preserving the original "no auth, localhost only" behavior. No breakage.
    - Non-empty -> every request must present the key in EITHER header:
          Authorization: Bearer <key>
          X-API-Key: <key>
      The presented value is compared to the configured key in constant time
      (`hmac.compare_digest`). A missing / malformed / mismatched key yields a
      401 response using the standard API envelope
      (`{"data": null, "error": {"code": "UNAUTHORIZED", ...}}`).
    - Exempt paths (always reachable without a key): the `/health` probe and
      the interactive docs (`/docs`, `/redoc`, `/openapi.json`,
      `/docs/oauth2-redirect`).
    - CORS preflight (`OPTIONS`) is allowed through so browser clients can
      complete preflight; the subsequent real request is still gated.
    - The key is NEVER logged.

Note:
    Fernet at-rest encryption helpers for `accounts`/`settings` secrets remain
    planned for a later phase and are intentionally not implemented here yet.

Connected modules:
    - Wired into the app by: backend.app.main via `add_auth_middleware(app)`.
"""

from __future__ import annotations

import hmac

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.app.core.config import settings

_BEARER_PREFIX = "Bearer "

# Paths that must stay reachable without a key: liveness probe + API docs.
_EXEMPT_PATHS = frozenset(
    {
        "/health",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/openapi.json",
    }
)


def _extract_presented_key(request: Request) -> str | None:
    """Return the key presented via `Authorization: Bearer` or `X-API-Key`."""
    authorization = request.headers.get("Authorization")
    if authorization and authorization.startswith(_BEARER_PREFIX):
        return authorization[len(_BEARER_PREFIX) :].strip()
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key.strip()
    return None


def _unauthorized_response() -> JSONResponse:
    """401 in the standard API envelope. The key itself is never included."""
    return JSONResponse(
        status_code=401,
        content={
            "data": None,
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Missing or invalid API key",
                "details": None,
            },
        },
    )


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """Require a static bearer token on every non-exempt request.

    Reads `settings.BACKEND_API_KEY` per-request so the gate can be toggled via
    environment/config without rebuilding the middleware. When the configured
    key is empty the middleware is a pass-through (auth disabled).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        expected_key = settings.BACKEND_API_KEY
        # Empty configured key => auth disabled (default localhost behavior).
        if not expected_key:
            return await call_next(request)
        # Let CORS preflight through; the actual request is still authenticated.
        if request.method == "OPTIONS":
            return await call_next(request)
        # Health probe and API docs stay open.
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)
        presented_key = _extract_presented_key(request)
        if presented_key is None or not hmac.compare_digest(
            presented_key, expected_key
        ):
            return _unauthorized_response()
        return await call_next(request)


def add_auth_middleware(app: FastAPI) -> None:
    """Attach the optional API-key auth middleware to the FastAPI app.

    Safe to call unconditionally: when `settings.BACKEND_API_KEY` is empty the
    middleware passes every request through, so wiring it in never changes the
    default (auth-off) behavior.
    """
    app.add_middleware(ApiKeyAuthMiddleware)
