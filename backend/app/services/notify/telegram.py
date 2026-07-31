"""Async Telegram Bot notification client."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from typing import Any

import aiohttp
import certifi

from backend.app.core.config import settings


@dataclass(frozen=True, slots=True)
class TelegramSendResult:
    sent: bool
    skipped: bool
    message: str
    payload: dict[str, Any] | None = None


class TelegramSendError(RuntimeError):
    """Raised when Telegram returns a non-OK response."""


class TelegramClient:
    """Small aiohttp wrapper around Telegram Bot API."""

    def __init__(
        self,
        *,
        bot_token: str | None = None,
        chat_id: str | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN.get_secret_value()
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.timeout_seconds = timeout_seconds

    async def _call(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Telegram Bot API 호출 공통부 — 토큰은 URL에만 쓰고 로그에 남기지 않는다."""
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        timeout = aiohttp.ClientTimeout(
            total=timeout_seconds or self.timeout_seconds
        )
        connector = aiohttp.TCPConnector(ssl=_ssl_context())
        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            ) as session:
                async with session.post(url, json=payload) as response:
                    body = await response.json(content_type=None)
                    if response.status >= 400 or not body.get("ok", False):
                        raise TelegramSendError(
                            f"Telegram {method} failed: status={response.status}"
                            f" body={body}"
                        )
                    return body
        except aiohttp.ClientConnectorCertificateError as exc:
            raise TelegramSendError(
                "Telegram TLS certificate verification failed. If your network uses "
                "a security proxy with a private root certificate, set "
                "TELEGRAM_CA_BUNDLE_PATH to that PEM bundle. For a short local "
                "diagnostic only, set TELEGRAM_SSL_VERIFY=false."
            ) from exc
        except TimeoutError as exc:
            raise TelegramSendError(f"Telegram {method} timed out.") from exc
        except aiohttp.ClientError as exc:
            raise TelegramSendError(f"Telegram HTTP client error: {exc}") from exc

    async def send_markdown(
        self,
        text: str,
        *,
        disable_web_page_preview: bool = True,
        reply_markup: dict[str, Any] | None = None,
    ) -> TelegramSendResult:
        """Send a Markdown-formatted message, or skip if credentials are absent.

        ``reply_markup``: 인라인 키보드(승인/거절 버튼) — 없으면 기존과 동일.
        """
        if not self.bot_token or not self.chat_id:
            return TelegramSendResult(
                sent=False,
                skipped=True,
                message="Telegram credentials are not configured.",
            )
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        body = await self._call("sendMessage", payload)
        return TelegramSendResult(
            sent=True, skipped=False, message="Telegram message sent.",
            payload=body,
        )

    async def edit_message(
        self,
        message_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        """승인/거절 결과를 원 메시지에 반영 (키보드 교체 포함)."""
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        await self._call("editMessageText", payload)

    async def answer_callback(
        self, callback_query_id: str, text: str = ""
    ) -> None:
        await self._call(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text[:190]},
        )

    async def get_updates(
        self, offset: int, *, timeout: int = 25
    ) -> list[dict[str, Any]]:
        """long polling — 콜백(버튼 탭) 수신. 공인 IP/웹훅 불필요."""
        body = await self._call(
            "getUpdates",
            {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": ["callback_query"],
            },
            timeout_seconds=timeout + 10,
        )
        result = body.get("result")
        return result if isinstance(result, list) else []


async def send_markdown(text: str) -> TelegramSendResult:
    """Convenience function used by batch jobs."""

    return await TelegramClient().send_markdown(text)


def _ssl_context() -> ssl.SSLContext | bool:
    if not settings.TELEGRAM_SSL_VERIFY:
        return False

    ca_bundle_path = settings.telegram_ca_bundle_path
    if ca_bundle_path is not None:
        if not ca_bundle_path.exists() or not ca_bundle_path.is_file():
            raise TelegramSendError(
                f"TELEGRAM_CA_BUNDLE_PATH is not a file: {ca_bundle_path}"
            )
        return ssl.create_default_context(cafile=str(ca_bundle_path))

    return ssl.create_default_context(cafile=certifi.where())
