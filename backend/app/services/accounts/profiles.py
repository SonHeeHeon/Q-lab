"""계좌 프로파일 시드·검증 — 자격증명 없음(메타 전용).

기본 슬리브 매핑은 스펙(.omc/plan/2026-07-31_five-account-live-quant.md)의
초기값이며 SP5 계좌별 백테스트 결과로 갱신된다. 전략 이름은
_first_loadable로 고른다: 소유자 환경(프라이빗 튜닝 존재)과 OSS 체크아웃
(공개판만) 어느 쪽에서도 로드 가능한 이름이 시드되도록.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select

from backend.app.services.batch.daily_analysis import load_strategy
from shared.db.models import AccountProfile, Setting

logger = logging.getLogger(__name__)

ACCOUNT_KEYS: list[str] = [
    "KIS:PAPER", "KIS:REAL", "KIS:ISA",
    "KIS:DC", "KIS:IRP", "KIS:PENSION", "TOSS:MAIN",
]

DEFAULT_PROFILE_TYPES: dict[str, str] = {
    "KIS:PAPER": "PERSONAL",  # 모의 = 개인 프로파일로 기능 검증
    "KIS:REAL": "PERSONAL",
    "KIS:ISA": "ISA",
    "KIS:DC": "DC",
    "KIS:IRP": "IRP",
    "KIS:PENSION": "PENSION",
    "TOSS:MAIN": "US",
}

_SAFE_HOLD_CODE = "153130"  # KODEX 단기채권 — DC/IRP 안전 32% 고정 보유


def _first_loadable(*names: str) -> str:
    for name in names:
        try:
            load_strategy(name)
        except FileNotFoundError:
            continue
        return name
    return names[-1]  # 전부 실패 시 마지막(공개 기본판) 이름을 그대로 시드


def default_sleeves(account_key: str) -> list[dict]:
    profile = DEFAULT_PROFILE_TYPES[account_key]
    if profile == "PERSONAL":
        return [{"type": "strategy",
                 "name": _first_loadable("qlab_alpha_v2", "value_v1"),
                 "weight": 1.0}]
    if profile == "ISA":
        return [
            {"type": "strategy",
             "name": _first_loadable("qlab_alpha_v2", "value_v1"), "weight": 0.7},
            {"type": "strategy", "name": "etf_rotation_kr", "weight": 0.3},
        ]
    if profile in ("DC", "IRP"):
        return [
            {"type": "strategy", "name": "dc_risk_rotation_kr", "weight": 0.68},
            {"type": "hold", "code": _SAFE_HOLD_CODE, "weight": 0.32},
        ]
    if profile == "PENSION":
        return [{"type": "strategy", "name": "dc_risk_rotation_kr", "weight": 1.0}]
    if profile == "US":
        return [
            {"type": "strategy",
             "name": _first_loadable("us_value", "us_stock_v1"), "weight": 0.55},
            {"type": "strategy", "name": "etf_rotation_us", "weight": 0.45},
        ]
    raise ValueError(f"unknown profile type: {profile}")


def validate_sleeves(sleeves: list[dict]) -> list[dict]:
    """형식·합계 검증 + 정규화. 실패 시 ValueError(사용자 메시지)."""
    if not sleeves:
        raise ValueError("슬리브가 비어 있습니다")
    total = 0.0
    for s in sleeves:
        kind = s.get("type")
        weight = s.get("weight")
        if not isinstance(weight, (int, float)) or weight < 0:
            raise ValueError(f"잘못된 비중: {weight!r}")
        if kind == "strategy":
            if not s.get("name"):
                raise ValueError("strategy 슬리브에 name이 없습니다")
        elif kind == "hold":
            code = s.get("code", "")
            if not (isinstance(code, str) and code):
                raise ValueError("hold 슬리브에 code가 없습니다")
        else:
            raise ValueError(f"알 수 없는 슬리브 타입: {kind!r}")
        total += float(weight)
    if abs(total - 1.0) > 0.01:
        raise ValueError(f"비중 합이 100%가 아닙니다 (합={total:.3f})")
    # 반올림 오차 정규화
    return [{**s, "weight": float(s["weight"]) / total} for s in sleeves]


async def ensure_account_profiles(session) -> None:
    """누락된 계좌 프로파일 행을 기본값으로 시드(존재 행은 불변)."""
    existing = {
        row.account_key
        for row in (await session.execute(select(AccountProfile))).scalars()
    }
    missing = [key for key in ACCOUNT_KEYS if key not in existing]
    if not missing:
        return
    for key in missing:
        broker, _, acct = key.partition(":")
        session.add(AccountProfile(
            account_key=key,
            broker=broker,
            account_type=acct if broker == "KIS" else None,
            profile_type=DEFAULT_PROFILE_TYPES[key],
            quant_enabled=False,  # 스펙: 전 계좌 기본 OFF
            sleeves_json=json.dumps(default_sleeves(key), ensure_ascii=False),
        ))
    await session.commit()
    logger.info("account profiles seeded: %s", missing)


async def is_live_quant_unlocked(session) -> bool:
    """라이브 잠금 상태 — Setting("live_quant_unlocked")=="true"일 때만 해제."""
    row = await session.get(Setting, "live_quant_unlocked")
    return bool(row and str(row.value).strip().lower() == "true")
