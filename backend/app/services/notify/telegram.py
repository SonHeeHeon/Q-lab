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

    async def send_markdown(
        self,
        text: str,
        *,
        disable_web_page_preview: bool = True,
    ) -> TelegramSendResult:
        """Send a Markdown-formatted message, or skip if credentials are absent."""

        if not self.bot_token or not self.chat_id:
            return TelegramSendResult(
                sent=False,
                skipped=True,
                message="Telegram credentials are not configured.",
            )

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": disable_web_page_preview,
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
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
                            f"Telegram send failed: status={response.status} body={body}"
                        )
                    return TelegramSendResult(
                        sent=True,
                        skipped=False,
                        message="Telegram message sent.",
                        payload=body,
                    )
        except aiohttp.ClientConnectorCertificateError as exc:
            raise TelegramSendError(
                "Telegram TLS certificate verification failed. If your network uses "
                "a security proxy with a private root certificate, set "
                "TELEGRAM_CA_BUNDLE_PATH to that PEM bundle. For a short local "
                "diagnostic only, set TELEGRAM_SSL_VERIFY=false."
            ) from exc
        except TimeoutError as exc:
            raise TelegramSendError("Telegram send timed out.") from exc
        except aiohttp.ClientError as exc:
            raise TelegramSendError(f"Telegram HTTP client error: {exc}") from exc


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
