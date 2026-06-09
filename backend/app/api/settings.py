"""Settings API for local single-user configuration."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings, settings
from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.kis.rest_client import KISRestClient
from backend.app.services.notify.telegram import TelegramClient
from research.universe.kosdaq150 import (
    KOSDAQ150_CODES_FILE,
    KOSDAQ150RefreshResult,
    refresh_kosdaq150_codes_file,
)
from research.universe.kospi200 import (
    DEFAULT_CODES_FILE,
    KOSPI200RefreshResult,
    refresh_kospi200_codes_file,
)
from shared.db.models import Account, Setting
from shared.db.session import get_service_session
from shared.domain.account import AccountType

router = APIRouter(prefix="/api/settings", tags=["settings"])


class AccountCredentialsRequest(BaseModel):
    app_key: str = Field(min_length=1)
    app_secret: str = Field(min_length=1)
    account_no: str = Field(min_length=1)


class KisAccountStatusResponse(BaseModel):
    account_type: AccountType
    has_credentials: bool
    token_valid: bool
    last_token_issued_at: datetime | None = None
    last_error: str | None = None
    account_no_masked: str | None = None


class KOSPI200UniverseStatusResponse(BaseModel):
    path: str
    exists: bool
    count: int
    updated_at: datetime | None = None
    krx_credentials_configured: bool


class KOSPI200UniverseRefreshResponse(BaseModel):
    as_of: Date
    source: str
    source_status: str
    krx_credentials_configured: bool
    path: str
    previous_count: int
    current_count: int
    added: list[str]
    removed: list[str]
    updated: bool
    message: str
    summary: str


class AppSettingsResponse(BaseModel):
    accounts: list[KisAccountStatusResponse]
    default_drop_threshold_pct: float
    telegram_chat_id: str | None
    telegram_token_masked: str
    llm_provider: str
    llm_model: str
    llm_api_key_masked: str
    llm_cache_ttl_hours: int
    kospi200_universe: KOSPI200UniverseStatusResponse
    kosdaq150_universe: KOSPI200UniverseStatusResponse


class TestResultResponse(BaseModel):
    ok: bool
    message: str | None = None
    details: dict[str, Any] | None = None


@router.get("", response_model=ApiEnvelope[AppSettingsResponse])
async def get_settings(
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[AppSettingsResponse]:
    rows = await _settings_map(session)
    accounts = await _account_statuses(session)
    data = AppSettingsResponse(
        accounts=accounts,
        default_drop_threshold_pct=float(rows.get("default_drop_threshold_pct", "5.0")),
        telegram_chat_id=rows.get("telegram_chat_id") or settings.TELEGRAM_CHAT_ID or None,
        telegram_token_masked=_mask_secret(
            rows.get("telegram_bot_token")
            or settings.TELEGRAM_BOT_TOKEN.get_secret_value()
        ),
        llm_provider=rows.get("llm_provider") or settings.LLM_PROVIDER,
        llm_model=rows.get("llm_model") or settings.LLM_MODEL,
        llm_api_key_masked=_mask_secret(
            rows.get("openai_api_key") or settings.OPENAI_API_KEY.get_secret_value()
        ),
        llm_cache_ttl_hours=int(rows.get("llm_cache_ttl_hours", settings.LLM_CACHE_TTL_HOURS)),
        kospi200_universe=_kospi200_status(),
        kosdaq150_universe=_kosdaq150_status(),
    )
    return ApiEnvelope(data=data, error=None)


@router.patch("", response_model=ApiEnvelope[dict[str, Any]])
async def patch_settings(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[dict[str, Any]]:
    test_telegram = bool(payload.pop("__test_telegram", False))
    allowed_keys = {
        "default_drop_threshold_pct",
        "telegram_chat_id",
        "telegram_bot_token",
        "llm_provider",
        "llm_model",
        "openai_api_key",
        "llm_cache_ttl_hours",
    }
    updates = {
        key: str(value)
        for key, value in payload.items()
        if key in allowed_keys and value is not None
    }
    if updates:
        await _upsert_settings(session, updates)

    result: dict[str, Any] = {"updated": sorted(updates)}
    if test_telegram:
        rows = await _settings_map(session)
        telegram = TelegramClient(
            bot_token=rows.get("telegram_bot_token")
            or settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
            chat_id=rows.get("telegram_chat_id") or settings.TELEGRAM_CHAT_ID,
        )
        send_result = await telegram.send_markdown("Q-Lab Telegram settings test")
        result["telegram"] = {
            "sent": send_result.sent,
            "skipped": send_result.skipped,
            "message": send_result.message,
        }
    return ApiEnvelope(data=result, error=None)


@router.post("/accounts/{account_type}", response_model=ApiEnvelope[dict[str, Any]])
async def update_account(
    account_type: AccountType,
    payload: AccountCredentialsRequest,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[dict[str, Any]]:
    stmt = insert(Account).values(
        type=account_type.value,
        app_key=payload.app_key,
        app_secret=payload.app_secret,
        account_no=payload.account_no,
        is_active=True,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Account.type],
        set_={
            "app_key": stmt.excluded.app_key,
            "app_secret": stmt.excluded.app_secret,
            "account_no": stmt.excluded.account_no,
            "is_active": True,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return ApiEnvelope(
        data={"saved": True, "account_type": account_type.value},
        error=None,
    )


@router.post(
    "/accounts/{account_type}/test",
    response_model=ApiEnvelope[TestResultResponse],
)
async def test_account(
    account_type: AccountType,
    session: AsyncSession = Depends(get_service_session),
) -> ApiEnvelope[TestResultResponse]:
    account = await _account_config(session, account_type)
    if account is None:
        return ApiEnvelope(
            data=TestResultResponse(
                ok=False,
                message=f"{account_type.value} credentials are not configured.",
            ),
            error=None,
        )

    app_settings = _settings_with_account(account_type, account)
    try:
        portfolio = await KISRestClient(app_settings=app_settings).get_balance(account_type)
    except Exception as exc:
        return ApiEnvelope(
            data=TestResultResponse(
                ok=False,
                message=str(exc),
                details={"account_type": account_type.value},
            ),
            error=None,
        )

    return ApiEnvelope(
        data=TestResultResponse(
            ok=True,
            message="KIS account test succeeded.",
            details={
                "account_type": account_type.value,
                "positions": len(portfolio.positions),
                "summary": portfolio.summary.model_dump(mode="json"),
            },
        ),
        error=None,
    )


@router.post(
    "/universe/kospi200/refresh",
    response_model=ApiEnvelope[KOSPI200UniverseRefreshResponse],
    responses={
        203: {
            "description": (
                "Refreshed successfully from a non-authoritative fallback "
                "after official KRX sources failed."
            )
        },
        206: {
            "description": (
                "Refreshed successfully from an approximate, cached, or manual "
                "fallback source."
            )
        },
        503: {"description": "No sufficiently complete KOSPI200 source was available."},
    },
)
async def refresh_kospi200_universe(
    response: Response,
    as_of: Date | None = Query(default=None),
) -> ApiEnvelope[KOSPI200UniverseRefreshResponse]:
    """Fetch current KOSPI200 members and update data/manual/kospi200_codes.csv."""

    try:
        result = await asyncio.to_thread(
            refresh_kospi200_codes_file,
            as_of=as_of,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response.status_code = _kospi200_refresh_status_code(result.source)
    return ApiEnvelope(data=_kospi200_refresh_response(result), error=None)


@router.post(
    "/universe/kosdaq150/refresh",
    response_model=ApiEnvelope[KOSPI200UniverseRefreshResponse],
    responses={
        206: {
            "description": (
                "Refreshed successfully from an approximate, cached, or manual "
                "fallback source."
            )
        },
        503: {"description": "No sufficiently complete KOSDAQ150 source was available."},
    },
)
async def refresh_kosdaq150_universe(
    response: Response,
    as_of: Date | None = Query(default=None),
) -> ApiEnvelope[KOSPI200UniverseRefreshResponse]:
    """Fetch current KOSDAQ150 members and update data/manual/kosdaq150_codes.csv."""

    try:
        result = await asyncio.to_thread(
            refresh_kosdaq150_codes_file,
            as_of=as_of,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response.status_code = _kospi200_refresh_status_code(result.source)
    return ApiEnvelope(data=_kosdaq150_refresh_response(result), error=None)


async def _settings_map(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(select(Setting))
    return {row.key: row.value for row in result.scalars()}


async def _upsert_settings(session: AsyncSession, values: dict[str, str]) -> None:
    now = datetime.now()
    rows = [
        {
            "key": key,
            "value": value,
            "updated_at": now,
        }
        for key, value in values.items()
    ]
    stmt = insert(Setting).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Setting.key],
        set_={
            "value": stmt.excluded.value,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await session.execute(stmt)
    await session.commit()


async def _account_statuses(session: AsyncSession) -> list[KisAccountStatusResponse]:
    statuses: list[KisAccountStatusResponse] = []
    for account_type in AccountType:
        account = await _account_config(session, account_type)
        has_credentials = bool(
            account
            and account.app_key
            and account.app_secret
            and account.account_no
        )
        statuses.append(
            KisAccountStatusResponse(
                account_type=account_type,
                has_credentials=has_credentials,
                token_valid=False,
                account_no_masked=_mask_account_no(account.account_no if account else ""),
            )
        )
    return statuses


async def _account_config(
    session: AsyncSession,
    account_type: AccountType,
) -> Account | None:
    db_account = await session.get(Account, account_type.value)
    if db_account is not None and db_account.app_key != "[managed-by-env]":
        return db_account

    env_account = settings.kis_account(account_type)
    if not env_account.app_key.get_secret_value() or not env_account.app_secret.get_secret_value():
        return db_account
    return Account(
        type=account_type.value,
        app_key=env_account.app_key.get_secret_value(),
        app_secret=env_account.app_secret.get_secret_value(),
        account_no=env_account.account_no,
        is_active=env_account.is_active,
    )


def _settings_with_account(account_type: AccountType, account: Account) -> Settings:
    prefix = f"KIS_{account_type.value}"
    return Settings(
        **{
            f"{prefix}_APP_KEY": account.app_key,
            f"{prefix}_APP_SECRET": account.app_secret,
            f"{prefix}_ACCOUNT_NO": account.account_no,
        }
    )


def _mask_secret(value: str | None) -> str:
    if not value:
        return ""
    return "••••••••"


def _mask_account_no(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.replace("-", "")
    if len(normalized) <= 4:
        return "••••"
    return f"{normalized[:2]}••••{normalized[-2:]}"


def _kospi200_status(path: Path = DEFAULT_CODES_FILE) -> KOSPI200UniverseStatusResponse:
    exists = path.exists()
    count = 0
    updated_at: datetime | None = None
    if exists:
        try:
            text = path.read_text(encoding="utf-8-sig")
            count = len(dict.fromkeys(re.findall(r"(?<!\d)\d{6}(?!\d)", text)))
            updated_at = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            count = 0
            updated_at = None
    return KOSPI200UniverseStatusResponse(
        path=str(path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path),
        exists=exists,
        count=count,
        updated_at=updated_at,
        krx_credentials_configured=_krx_credentials_configured(),
    )


def _kosdaq150_status(path: Path = KOSDAQ150_CODES_FILE) -> KOSPI200UniverseStatusResponse:
    exists = path.exists()
    count = 0
    updated_at: datetime | None = None
    if exists:
        try:
            text = path.read_text(encoding="utf-8-sig")
            count = len(dict.fromkeys(re.findall(r"(?<!\d)\d{6}(?!\d)", text)))
            updated_at = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            count = 0
            updated_at = None
    return KOSPI200UniverseStatusResponse(
        path=str(path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path),
        exists=exists,
        count=count,
        updated_at=updated_at,
        krx_credentials_configured=_krx_credentials_configured(),
    )


def _kospi200_refresh_response(
    result: KOSPI200RefreshResult,
) -> KOSPI200UniverseRefreshResponse:
    path = result.path
    krx_credentials_configured = _krx_credentials_configured()
    source_status = _kospi200_source_status(result.source)
    message = _kospi200_refresh_message(
        result,
        krx_credentials_configured=krx_credentials_configured,
    )
    return KOSPI200UniverseRefreshResponse(
        as_of=result.as_of,
        source=result.source,
        source_status=source_status,
        krx_credentials_configured=krx_credentials_configured,
        path=str(path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path),
        previous_count=result.previous_count,
        current_count=result.current_count,
        added=result.added,
        removed=result.removed,
        updated=result.updated,
        message=message,
        summary=(
            f"KOSPI200 refresh {source_status}: source={result.source}, "
            f"codes={result.current_count}, updated={result.updated}, "
            f"added={len(result.added)}, removed={len(result.removed)}, "
            f"krx_credentials_configured={krx_credentials_configured}"
        ),
    )


def _kosdaq150_refresh_response(
    result: KOSDAQ150RefreshResult,
) -> KOSPI200UniverseRefreshResponse:
    path = result.path
    krx_credentials_configured = _krx_credentials_configured()
    source_status = _kospi200_source_status(result.source)
    message = _kosdaq150_refresh_message(
        result,
        krx_credentials_configured=krx_credentials_configured,
    )
    return KOSPI200UniverseRefreshResponse(
        as_of=result.as_of,
        source=result.source,
        source_status=source_status,
        krx_credentials_configured=krx_credentials_configured,
        path=str(path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path),
        previous_count=result.previous_count,
        current_count=result.current_count,
        added=result.added,
        removed=result.removed,
        updated=result.updated,
        message=message,
        summary=(
            f"KOSDAQ150 refresh {source_status}: source={result.source}, "
            f"codes={result.current_count}, updated={result.updated}, "
            f"added={len(result.added)}, removed={len(result.removed)}, "
            f"krx_credentials_configured={krx_credentials_configured}"
        ),
    )


def _kospi200_refresh_status_code(source: str) -> int:
    if source.startswith(("pykrx:", "fdr:")):
        return 200
    if source.startswith("wikipedia:"):
        return 203
    return 206


def _kospi200_source_status(source: str) -> str:
    if source.startswith("pykrx:"):
        return "official"
    if source.startswith("fdr:"):
        return "krx_snapshot_fallback"
    if source.startswith("wikipedia:"):
        return "non_authoritative_fallback"
    if source.startswith("approx:"):
        return "approximation_fallback"
    return "fallback"


def _kospi200_refresh_message(
    result: KOSPI200RefreshResult,
    *,
    krx_credentials_configured: bool,
) -> str:
    if result.source.startswith("pykrx:"):
        return "KOSPI200 list was refreshed from the official KRX/pykrx source."
    if result.source.startswith("fdr:"):
        prefix = _krx_fallback_reason(krx_credentials_configured)
        return (
            f"{prefix} KOSPI200 list was refreshed from "
            "FinanceDataReader's KRX index snapshot."
        )
    if result.source.startswith("wikipedia:"):
        prefix = _krx_fallback_reason(krx_credentials_configured)
        return (
            f"{prefix} FinanceDataReader KRX snapshot lookup also failed; KOSPI200 "
            "list was refreshed from Wikipedia as a non-authoritative last-resort "
            "fallback."
        )
    if result.source.startswith("approx:"):
        prefix = _krx_fallback_reason(krx_credentials_configured)
        return (
            f"{prefix} KOSPI200 list was approximated "
            "from KOSPI market-cap ranking."
        )
    return f"KOSPI200 list was refreshed from fallback source: {result.source}."


def _kosdaq150_refresh_message(
    result: KOSDAQ150RefreshResult,
    *,
    krx_credentials_configured: bool,
) -> str:
    if result.source.startswith("pykrx:"):
        return "KOSDAQ150 list was refreshed from the official KRX/pykrx source."
    if result.source.startswith("fdr:"):
        prefix = _krx_fallback_reason(krx_credentials_configured)
        return (
            f"{prefix} KOSDAQ150 list was refreshed from "
            "FinanceDataReader's KRX index snapshot."
        )
    if result.source.startswith("approx:"):
        prefix = _krx_fallback_reason(krx_credentials_configured)
        return (
            f"{prefix} KOSDAQ150 list was approximated "
            "from KOSDAQ market-cap ranking."
        )
    return f"KOSDAQ150 list was refreshed from fallback source: {result.source}."


def _krx_credentials_configured() -> bool:
    krx_id = os.getenv("KRX_ID") or settings.KRX_ID
    krx_pw = os.getenv("KRX_PW") or settings.KRX_PW.get_secret_value()
    return bool(krx_id and krx_pw)


def _krx_fallback_reason(krx_credentials_configured: bool) -> str:
    if krx_credentials_configured:
        return (
            "Official KRX/pykrx lookup failed even though KRX credentials are "
            "configured;"
        )
    return (
        "KRX credential unavailable in this server process; official pykrx "
        "lookup could not authenticate;"
    )
