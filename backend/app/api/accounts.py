"""계좌 프로파일 API — 목록/마킹/퀀트 토글/슬리브 비중.

라이브 잠금: Setting("live_quant_unlocked") != "true" 인 동안
KIS:PAPER 외 계좌의 quant_enabled=true는 403 (스펙 §라이브 잠금 —
.omc/plan/2026-07-31_five-account-live-quant.md).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.accounts.profiles import (
    ensure_account_profiles,
    is_live_quant_unlocked,
    validate_sleeves,
)
from shared.db.models import AccountProfile
from shared.db.session import service_session
from shared.domain.account import AccountType

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

PROFILE_TYPES = {"PERSONAL", "ISA", "DC", "IRP", "PENSION", "US"}


class AccountPatch(BaseModel):
    profile_type: str | None = None
    quant_enabled: bool | None = None
    sleeves: list[dict] | None = None


class LiveLockError(Exception):
    """실계좌 퀀트 ON 시도 — 라이브 잠금 중."""


def apply_account_patch(
    profile: AccountProfile, patch: AccountPatch, *, live_unlocked: bool
) -> AccountProfile:
    """순수 갱신 로직 — 잠금·검증 강제 (테스트 대상)."""
    if patch.profile_type is not None:
        if patch.profile_type not in PROFILE_TYPES:
            raise ValueError(f"알 수 없는 프로파일 타입: {patch.profile_type}")
        profile.profile_type = patch.profile_type
    if patch.sleeves is not None:
        profile.sleeves_json = json.dumps(
            validate_sleeves(patch.sleeves), ensure_ascii=False
        )
    if patch.quant_enabled is not None:
        if (
            patch.quant_enabled
            and profile.account_key != "KIS:PAPER"
            and not live_unlocked
        ):
            raise LiveLockError(
                "실계좌 퀀트는 잠금 상태입니다 — 실전 운용 사전작업 완료 후 해제"
            )
        profile.quant_enabled = patch.quant_enabled
    return profile


def _connected(profile: AccountProfile) -> bool:
    if profile.broker == "TOSS":
        return bool(settings.TOSS_CLIENT_ID)
    return settings.kis_account(AccountType(profile.account_type)).is_active


def _serialize(profile: AccountProfile) -> dict:
    return {
        "account_key": profile.account_key,
        "broker": profile.broker,
        "account_type": profile.account_type,
        "profile_type": profile.profile_type,
        "quant_enabled": profile.quant_enabled,
        "connected": _connected(profile),
        "sleeves": json.loads(profile.sleeves_json),
    }


@router.get("", response_model=ApiEnvelope[list[dict]])
async def list_accounts() -> ApiEnvelope[list[dict]]:
    async with service_session() as session:
        await ensure_account_profiles(session)
        rows = (
            (await session.execute(select(AccountProfile))).scalars().all()
        )
    order = {key: i for i, key in enumerate(
        ["KIS:PAPER", "KIS:REAL", "KIS:ISA", "KIS:DC", "KIS:IRP",
         "KIS:PENSION", "TOSS:MAIN"]
    )}
    rows = sorted(rows, key=lambda p: order.get(p.account_key, 99))
    return ApiEnvelope(data=[_serialize(p) for p in rows], error=None)


@router.patch("/{account_key:path}", response_model=ApiEnvelope[dict])
async def patch_account(account_key: str, patch: AccountPatch) -> ApiEnvelope[dict]:
    async with service_session() as session:
        await ensure_account_profiles(session)
        profile = await session.get(AccountProfile, account_key)
        if profile is None:
            raise HTTPException(404, f"unknown account: {account_key}")
        try:
            apply_account_patch(
                profile, patch,
                live_unlocked=await is_live_quant_unlocked(session),
            )
        except LiveLockError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        await session.commit()
        return ApiEnvelope(data=_serialize(profile), error=None)
