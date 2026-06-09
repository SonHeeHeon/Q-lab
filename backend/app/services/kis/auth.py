"""KIS OAuth access-token and WebSocket approval-key management."""

from __future__ import annotations

import asyncio
import json
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
import certifi

from backend.app.core.config import Settings, settings
from backend.app.services.kis.accounts import KISAccountRegistry
from shared.domain.account import AccountType, KISAccount

KST = ZoneInfo("Asia/Seoul")


class KISAuthError(RuntimeError):
    """Raised when KIS authentication cannot be completed."""


@dataclass(frozen=True, slots=True)
class TokenCacheStatus:
    account_type: AccountType
    cache_path: Path
    has_access_token: bool
    access_token_expires_at: datetime | None
    has_approval_key: bool
    approval_key_expires_at: datetime | None


class KISTokenManager:
    """Fetches and caches KIS REST access tokens and WS approval keys."""

    def __init__(
        self,
        app_settings: Settings = settings,
        registry: KISAccountRegistry | None = None,
    ) -> None:
        self._settings = app_settings
        self._registry = registry or KISAccountRegistry(app_settings)
        self._locks = {account_type: asyncio.Lock() for account_type in AccountType}

    async def get_access_token(self, account_type: AccountType) -> str:
        async with self._locks[account_type]:
            cache = self._read_cache(account_type)
            cached_token = cache.get("access_token")
            expires_at = self._parse_cached_datetime(
                cache.get("access_token_expires_at")
            )
            if cached_token and self._is_valid(expires_at):
                return cached_token
            return await self._refresh_access_token_locked(account_type)

    async def get_approval_key(self, account_type: AccountType) -> str:
        async with self._locks[account_type]:
            cache = self._read_cache(account_type)
            cached_key = cache.get("approval_key")
            expires_at = self._parse_cached_datetime(
                cache.get("approval_key_expires_at")
            )
            if cached_key and self._is_valid(expires_at):
                return cached_key
            return await self._refresh_approval_key_locked(account_type)

    async def refresh_access_token(self, account_type: AccountType) -> str:
        async with self._locks[account_type]:
            return await self._refresh_access_token_locked(account_type)

    async def refresh_approval_key(self, account_type: AccountType) -> str:
        async with self._locks[account_type]:
            return await self._refresh_approval_key_locked(account_type)

    def cache_status(self, account_type: AccountType) -> TokenCacheStatus:
        cache = self._read_cache(account_type)
        return TokenCacheStatus(
            account_type=account_type,
            cache_path=self._cache_path(account_type),
            has_access_token=bool(cache.get("access_token")),
            access_token_expires_at=self._parse_cached_datetime(
                cache.get("access_token_expires_at")
            ),
            has_approval_key=bool(cache.get("approval_key")),
            approval_key_expires_at=self._parse_cached_datetime(
                cache.get("approval_key_expires_at")
            ),
        )

    async def _refresh_access_token_locked(self, account_type: AccountType) -> str:
        account_config = self._registry.get(account_type)
        account = account_config.account
        self._validate_account(account)

        url = f"{account_config.endpoints.rest_base_url}/oauth2/tokenP"
        request_body = {
            "grant_type": "client_credentials",
            "appkey": account.app_key.get_secret_value(),
            "appsecret": account.app_secret.get_secret_value(),
        }
        response = await self._post_json(url, request_body)

        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise KISAuthError("KIS token response did not include access_token.")

        expires_at = self._extract_access_token_expiry(response)
        self._write_cache(
            account_type,
            {
                "access_token": access_token,
                "access_token_expires_at": self._format_datetime(expires_at),
            },
        )
        return access_token

    async def _refresh_approval_key_locked(self, account_type: AccountType) -> str:
        account_config = self._registry.get(account_type)
        account = account_config.account
        self._validate_account(account)

        url = f"{account_config.endpoints.rest_base_url}/oauth2/Approval"
        request_body = {
            "grant_type": "client_credentials",
            "appkey": account.app_key.get_secret_value(),
            "secretkey": account.app_secret.get_secret_value(),
        }
        response = await self._post_json(url, request_body)

        approval_key = response.get("approval_key")
        if not isinstance(approval_key, str) or not approval_key:
            raise KISAuthError("KIS approval response did not include approval_key.")

        expires_at = self._utc_now() + timedelta(
            seconds=self._settings.KIS_APPROVAL_KEY_TTL_SECONDS
        )
        self._write_cache(
            account_type,
            {
                "approval_key": approval_key,
                "approval_key_expires_at": self._format_datetime(expires_at),
            },
        )
        return approval_key

    async def _post_json(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=self._settings.KIS_HTTP_TIMEOUT_SECONDS)
        connector = aiohttp.TCPConnector(ssl=self._ssl_context())
        headers = {"content-type": "application/json; charset=utf-8"}

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            ) as session:
                async with session.post(url, json=body, headers=headers) as response:
                    status = response.status
                    response_text = await response.text()
        except aiohttp.ClientConnectorCertificateError as exc:
            raise KISAuthError(
                "KIS TLS certificate verification failed. This usually means the "
                "local Python CA bundle is missing, or a network security proxy is "
                "injecting a self-signed certificate. The client now uses certifi by "
                "default; if this still fails, set KIS_CA_BUNDLE_PATH to your trusted "
                "proxy/root CA bundle. For a one-off local diagnostic only, run the "
                "verification script with --insecure-skip-ssl-verify."
            ) from exc
        except aiohttp.ClientConnectorError as exc:
            raise KISAuthError(f"Could not connect to KIS auth endpoint: {exc}") from exc
        except TimeoutError as exc:
            raise KISAuthError(
                f"KIS auth request timed out after "
                f"{self._settings.KIS_HTTP_TIMEOUT_SECONDS}s."
            ) from exc
        except aiohttp.ClientError as exc:
            raise KISAuthError(f"KIS auth HTTP client error: {exc}") from exc

        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise KISAuthError(
                f"KIS auth response was not JSON. HTTP {status}: "
                f"{response_text[:300]}"
            ) from exc

        if status >= 400:
            raise KISAuthError(f"KIS auth request failed. HTTP {status}: {payload}")

        if payload.get("rt_cd") not in (None, "0"):
            message = payload.get("msg1") or payload.get("msg_cd") or payload
            raise KISAuthError(f"KIS auth request was rejected: {message}")

        return payload

    def _ssl_context(self) -> ssl.SSLContext | bool:
        if not self._settings.KIS_SSL_VERIFY:
            return False

        ca_bundle_path = self._settings.kis_ca_bundle_path
        if ca_bundle_path is not None:
            if not ca_bundle_path.exists() or not ca_bundle_path.is_file():
                raise KISAuthError(
                    f"KIS_CA_BUNDLE_PATH is not a file: {ca_bundle_path}"
                )
            return ssl.create_default_context(cafile=str(ca_bundle_path))

        return ssl.create_default_context(cafile=certifi.where())

    def _extract_access_token_expiry(self, payload: dict[str, Any]) -> datetime:
        explicit_expiry = payload.get("access_token_token_expired")
        if isinstance(explicit_expiry, str) and explicit_expiry:
            parsed = self._parse_kis_datetime(explicit_expiry)
            if parsed is not None:
                return parsed

        expires_in = payload.get(
            "expires_in", self._settings.KIS_ACCESS_TOKEN_TTL_SECONDS
        )
        try:
            ttl_seconds = int(expires_in)
        except (TypeError, ValueError):
            ttl_seconds = self._settings.KIS_ACCESS_TOKEN_TTL_SECONDS
        return self._utc_now() + timedelta(seconds=ttl_seconds)

    def _cache_path(self, account_type: AccountType) -> Path:
        return self._settings.token_cache_dir / f"{account_type.value}.json"

    def _read_cache(self, account_type: AccountType) -> dict[str, Any]:
        path = self._cache_path(account_type)
        if not path.exists():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if isinstance(loaded, dict):
            return loaded
        return {}

    def _write_cache(self, account_type: AccountType, updates: dict[str, Any]) -> None:
        path = self._cache_path(account_type)
        path.parent.mkdir(parents=True, exist_ok=True)

        cache = self._read_cache(account_type)
        cache.update(
            {
                "account_type": account_type.value,
                "updated_at": self._format_datetime(self._utc_now()),
                **updates,
            }
        )

        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _is_valid(self, expires_at: datetime | None) -> bool:
        if expires_at is None:
            return False
        safety_buffer = timedelta(seconds=self._settings.KIS_TOKEN_SAFETY_BUFFER_SECONDS)
        return self._utc_now() + safety_buffer < expires_at

    def _validate_account(self, account: KISAccount) -> None:
        missing = []
        if not account.app_key.get_secret_value():
            missing.append(f"KIS_{account.type.value}_APP_KEY")
        if not account.app_secret.get_secret_value():
            missing.append(f"KIS_{account.type.value}_APP_SECRET")
        if not account.account_no:
            missing.append(f"KIS_{account.type.value}_ACCOUNT_NO")
        if missing:
            raise KISAuthError(
                f"Missing KIS credentials for {account.type.value}: "
                + ", ".join(missing)
            )

    def _parse_cached_datetime(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _parse_kis_datetime(self, value: str) -> datetime | None:
        normalized = value.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
            try:
                return (
                    datetime.strptime(normalized, fmt)
                    .replace(tzinfo=KST)
                    .astimezone(timezone.utc)
                )
            except ValueError:
                continue

        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        return parsed.astimezone(timezone.utc)

    def _format_datetime(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)


token_manager = KISTokenManager()
