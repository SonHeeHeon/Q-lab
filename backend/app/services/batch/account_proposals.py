"""N계좌 제안 오케스트레이터 — quant_enabled 계좌 × sleeves_json 순회.

기존 run_proposal_generation(전략 슬리브)을 재사용하고, hold 슬리브(고정
보유, 예: DC 안전 32% 단기채)는 이 모듈의 순수 diff로 처리한다. 전 계좌
quant_enabled 기본 false라 시드 직후엔 항상 skip — 라이브 잠금 해제·PAPER
검증 후에만 실동작한다(스펙 .omc/plan/2026-07-31_five-account-live-quant.md
§라이브 잠금). TOSS 분기(US 슬리브)는 run_toss_sleeves가 담당한다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select

from backend.app.services.accounts.profiles import ensure_account_profiles
from backend.app.services.batch.daily_analysis import (
    latest_research_price_date,
    load_strategy,
)
from backend.app.services.batch.proposal_generator import (
    ProposalDraft,
    _insert_proposals,
    _is_month_start,
    ramp_cap,
    run_carryover_generation,
    run_proposal_generation,
)
from backend.app.services.kis.rest_client import KISRestClient
from shared.db.models import AccountProfile
from shared.db.session import service_session
from shared.domain.account import AccountType

logger = logging.getLogger(__name__)

# 목표수량 ±5% 이내면 무거래(수수료 절약 밴드) — hold 슬리브 전용.
HOLD_REBALANCE_BAND = 0.05


def hold_sleeve_proposals(
    *, code: str, weight: float, nav: float,
    positions: dict[str, int], prices: dict[str, float],
) -> list[ProposalDraft]:
    """고정 보유 슬리브: 목표 = weight×nav ÷ 현재가, 밴드 밖이면 diff (순수)."""
    price = prices.get(code)
    if not price or price <= 0 or nav <= 0 or weight <= 0:
        return []
    target_qty = int((nav * weight) // price)
    current = positions.get(code, 0)
    if target_qty <= 0:
        delta = -current
    else:
        if abs(current - target_qty) <= max(1, int(target_qty * HOLD_REBALANCE_BAND)):
            return []
        delta = target_qty - current
    if delta == 0:
        return []
    side = "BUY" if delta > 0 else "SELL"
    return [ProposalDraft(
        code, side, abs(delta), price,
        {"rule": "REBALANCE", "hold": True, "target_qty": max(target_qty, 0)},
    )]


def scope_us_positions(
    positions: dict[str, int], universe: set[str]
) -> dict[str, int]:
    """US 보유를 슬리브 유니버스 소속으로 스코핑 — 티커 원형 유지(zfill 금지)."""
    return {code: qty for code, qty in positions.items() if code in universe}


def _dc_exposure_warning(
    *, risky_value: float, nav: float, profile_type: str
) -> str | None:
    """DC/IRP 위험자산 규제(≤70%) 노출 경고 — 제안과 별개의 감시선."""
    if profile_type not in ("DC", "IRP") or nav <= 0:
        return None
    ratio = risky_value / nav
    if ratio > 0.70:
        return (
            f"위험자산 노출 {ratio:.1%} > 규제 70% — 위험 슬리브 축소 필요"
            " (목표 68%)"
        )
    return None


async def _run_hold_sleeve(
    profile: AccountProfile, sleeve: dict, *, send_telegram: bool
) -> dict:
    """hold 슬리브 1개 실행 — 월초 앵커에서만 목표수량 diff를 제안으로 저장."""
    as_of = latest_research_price_date()
    if not _is_month_start(as_of):
        return {"skipped": "not month start"}

    account = AccountType(profile.account_type)
    client = KISRestClient()
    balance = await client.get_balance(account)

    positions: dict[str, int] = {}
    prices: dict[str, float] = {}
    holdings_value = 0.0
    for pos in balance.positions:
        code = pos.stock_code.zfill(6)
        qty = int(pos.quantity)
        if qty <= 0:
            continue
        positions[code] = qty
        price = float(pos.current_price or pos.avg_buy_price or 0)
        prices[code] = price
        holdings_value += qty * price
    nav = float(balance.summary.total_evaluation_amount or 0) or (
        holdings_value or 1.0
    )

    drafts = hold_sleeve_proposals(
        code=sleeve["code"], weight=float(sleeve["weight"]), nav=nav,
        positions=positions, prices=prices,
    )
    inserted = await _insert_proposals(
        drafts, account=account, as_of=as_of,
        strategy_name=f"hold_{sleeve['code']}",
    )
    return {
        "proposal_date": as_of.isoformat(),
        "mode": "HOLD_REBALANCE",
        "drafted": len(drafts),
        "inserted": inserted,
    }


async def run_all_account_proposals(*, send_telegram: bool = True) -> dict:
    """quant_enabled 계좌 순회 — 슬리브별 제안 생성 (실패는 슬리브 단위 격리)."""
    async with service_session() as session:
        await ensure_account_profiles(session)
        profiles = (
            await session.execute(
                select(AccountProfile).where(AccountProfile.quant_enabled)
            )
        ).scalars().all()

    if not profiles:
        summary = {"skipped": "no quant-enabled accounts"}
        logger.info("account proposals: %s", summary)
        return summary

    results: dict[str, dict] = {}
    for profile in profiles:
        sleeves = json.loads(profile.sleeves_json)
        if profile.broker == "TOSS":
            from backend.app.services.batch.account_proposals_toss import (
                run_toss_sleeves,
            )

            try:
                results[profile.account_key] = await run_toss_sleeves(
                    profile, sleeves, send_telegram=send_telegram
                )
            except Exception as exc:  # noqa: BLE001 — 계좌 단위 격리
                logger.exception("toss sleeves failed")
                results[profile.account_key] = {"error": str(exc)}
            continue

        account = AccountType(profile.account_type)
        as_of = latest_research_price_date()
        # 분할 진입 캡 — 퀀트 ON 후 경과 개월 기준 (0/미기록=캡 없음)
        cap = ramp_cap(
            profile.quant_enabled_at,
            int(profile.ramp_in_months or 0),
            now=datetime.now(),
        )
        acct_result: dict[str, dict] = {}
        for sleeve in sleeves:
            label = sleeve.get("name") or f"hold:{sleeve.get('code')}"
            try:
                if sleeve["type"] == "strategy":
                    # 현행 2슬리브 시맨틱 유지: MONTHLY 로테이션 전략은 월초
                    # 전체 diff만, 그 외(주식형)는 매일 규칙 모드.
                    monthly_rotation = (
                        load_strategy(sleeve["name"]).rebalance_freq == "MONTHLY"
                    )
                    if monthly_rotation and not _is_month_start(as_of):
                        # 미이행 이월: 이번 달 목표가 남아 있으면 재제안
                        acct_result[label] = await run_carryover_generation(
                            strategy_name=sleeve["name"],
                            account_type=account,
                            nav_weight=float(sleeve["weight"]),
                            send_telegram=send_telegram,
                            ramp_cap_value=cap,
                        )
                        continue
                    acct_result[label] = await run_proposal_generation(
                        strategy_name=sleeve["name"],
                        account_type=account,
                        full_rebalance=monthly_rotation,
                        nav_weight=float(sleeve["weight"]),
                        send_telegram=send_telegram,
                        ramp_cap_value=cap,
                    )
                else:
                    acct_result[label] = await _run_hold_sleeve(
                        profile, sleeve, send_telegram=send_telegram
                    )
            except Exception as exc:  # noqa: BLE001 — 슬리브 실패 격리
                logger.exception(
                    "sleeve %s/%s failed", profile.account_key, label
                )
                acct_result[label] = {"error": str(exc)}
        results[profile.account_key] = acct_result
    logger.info(
        "account proposals: %s", {k: list(v) for k, v in results.items()}
    )
    return results
