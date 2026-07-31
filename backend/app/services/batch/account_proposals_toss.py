"""Toss(US) 슬리브 제안 생성 — 기존 보유 흡수 (자문→승인형 통합).

KR 경로(run_proposal_generation)와 같은 시맨틱: 슬리브 스코핑(유니버스 소속)
→ MONTHLY 로테이션은 월초 전체 diff, 그 외 전략은 매일 규칙(브로커 평단 기준
손절 등) → market='US'로 저장(티커 원형, zfill 금지). 승인 시 Toss로 라우팅
되며, toss_is_mock=true인 동안 실체결은 없다(모의 응답).
"""
from __future__ import annotations

import logging

from backend.app.services.batch.daily_analysis import (
    latest_research_price_date,
    load_strategy,
)
from backend.app.services.accounts.auto_ramp import resolve_ramp_months
from backend.app.services.batch.account_proposals import scope_us_positions
from backend.app.services.batch.proposal_generator import (
    _filter_rejected,
    _insert_proposals,
    _is_month_start,
    _rejected_keys,
    _research_closes,
    _save_rebalance_target,
    apply_ramp_cap,
    build_carryover_drafts,
    build_rule_proposals,
    carryover_residual_notional,
    full_rebalance_proposals,
    load_rebalance_target,
    ramp_cap,
)
from backend.app.services.toss.rest_client import TossRestClient
from research.backtest.engine import (
    _allocate_equal_weight,
    _apply_abs_momentum_gate,
    apply_filters,
    get_universe,
    score_stocks,
)
from shared.db.session import research_db_path
from shared.domain.account import AccountType

logger = logging.getLogger(__name__)


async def run_toss_sleeves(
    profile, sleeves: list[dict], *, send_telegram: bool = True
) -> dict:
    """TOSS 계좌의 strategy 슬리브들을 실행 — 잔고 1회 조회 재사용."""
    as_of = latest_research_price_date()
    client = TossRestClient.from_settings_map({})
    balance = await client.get_balance()

    positions: dict[str, int] = {}
    entry_prices: dict[str, float] = {}
    prices: dict[str, float] = {}
    holdings_value = 0.0
    for pos in balance.positions:
        code = pos.stock_code  # US 티커 원형 유지 — zfill 금지
        qty = int(pos.quantity)
        if qty <= 0:
            continue
        positions[code] = qty
        entry_prices[code] = float(pos.avg_buy_price or 0)
        price = float(pos.current_price or pos.avg_buy_price or 0)
        prices[code] = price
        holdings_value += qty * price
    nav = float(balance.summary.total_evaluation_amount or 0) or (
        holdings_value or 1.0
    )

    results: dict[str, dict] = {}
    for sleeve in sleeves:
        if sleeve.get("type") != "strategy":
            results[f"hold:{sleeve.get('code')}"] = {
                "error": "hold 슬리브는 TOSS 미지원 (US 안전자산 슬리브 없음)"
            }
            continue
        name = sleeve["name"]
        try:
            results[name] = await _run_one_sleeve(
                name, float(sleeve["weight"]), as_of=as_of, nav=nav,
                positions=positions, entry_prices=entry_prices, prices=prices,
                profile=profile,
            )
        except Exception as exc:  # noqa: BLE001 — 슬리브 실패 격리
            logger.exception("toss sleeve %s failed", name)
            results[name] = {"error": str(exc)}
    return results


async def _run_one_sleeve(
    name: str, weight: float, *, as_of, nav: float,
    positions: dict[str, int], entry_prices: dict[str, float],
    prices: dict[str, float], profile=None,
) -> dict:
    strategy = load_strategy(name)
    universe = get_universe(strategy.universe, as_of=as_of, db_path=research_db_path)
    universe_set = set(universe)
    scoped = scope_us_positions(positions, universe_set)
    sleeve_nav = nav * weight
    monthly_rotation = strategy.rebalance_freq == "MONTHLY"
    account = AccountType.REAL  # US 제안의 계좌 표기 관례 (market='US'가 실질 구분)

    if monthly_rotation and not _is_month_start(as_of):
        # 미이행 이월 — KR 경로와 동일 시맨틱 (리뷰 P1-5)
        target = await load_rebalance_target(account, strategy.name, as_of)
        if not target:
            return {"skipped": "no saved target this period"}
        missing = sorted(set(target) - set(prices))
        prices = {**prices, **_research_closes(missing, as_of)}
        residual = carryover_residual_notional(target, scoped, prices)
        if residual < sleeve_nav * 0.01:
            return {"skipped": f"carryover residual below 1% ({residual:.0f})"}
        drafts = build_carryover_drafts(target, scoped, prices)
        drafts = [d for d in drafts if d.qty > 0 and d.last_price > 0]
        drafts = _filter_rejected(drafts, await _rejected_keys(account, as_of))
        if profile is not None:
            from datetime import datetime

            months = resolve_ramp_months(
                int(profile.ramp_in_months or 0), strategy.universe,
                enabled_at=profile.quant_enabled_at,
            )
            cap = ramp_cap(profile.quant_enabled_at, months, now=datetime.now())
            scoped_value = sum(scoped[c] * prices.get(c, 0.0) for c in scoped)
            drafts = apply_ramp_cap(
                drafts, cap=cap, sleeve_nav=sleeve_nav,
                holdings_value=scoped_value,
            )
        inserted, batch_id = await _insert_proposals(
            drafts, strategy=strategy, account=account, as_of=as_of, market="US",
        )
        return {
            "proposal_date": as_of.isoformat(), "mode": "CARRYOVER",
            "drafted": len(drafts), "inserted": inserted,
            "residual": round(residual),
        }

    if monthly_rotation:
        warnings: list[str] = []
        scored = score_stocks(
            universe, strategy.factors, as_of=as_of, db_path=research_db_path,
            warnings=warnings, groups=strategy.groups,
            min_groups=strategy.min_groups, winsor_pct=strategy.winsor_pct,
            clip_z=strategy.clip_z,
        )
        scored = apply_filters(
            scored, strategy.filters, as_of=as_of,
            db_path=research_db_path, warnings=warnings,
        )
        ranked = [str(c) for c in scored.index]
        selected = ranked[: strategy.top_n]
        slots: int | None = None
        if strategy.abs_momentum_gate:
            slots = len(selected)
            selected = _apply_abs_momentum_gate(
                selected, scored, factor_name=strategy.abs_momentum_factor,
                as_of=as_of, db_path=research_db_path, warnings=warnings,
            )
        # 목표 종목의 가격 공백을 연구 종가로 보강 (티커 원형)
        missing = sorted(set(selected) - set(prices))
        prices = {**prices, **_research_closes(missing, as_of)}
        drafts = full_rebalance_proposals(
            positions=scoped, prices=prices, nav=sleeve_nav,
            selected=selected, slots=slots,
        )
        # 이월(carryover)용 주기 목표 저장 — KR 경로와 동일 (리뷰 P1-5)
        target_map = _allocate_equal_weight(
            selected, nav=sleeve_nav, prices=prices, exposure=1.0, slots=slots,
        )
        await _save_rebalance_target(account, strategy.name, as_of, target_map)
    else:
        drafts = build_rule_proposals(
            strategy=strategy, positions=scoped, entry_prices=entry_prices,
            prices=prices, nav=sleeve_nav,
        )

    drafts = [d for d in drafts if d.qty > 0 and d.last_price > 0]
    # 거절 존중 — 이번 주기 거절 (종목, 방향) 재제안 억제(위험규칙 예외).
    drafts = _filter_rejected(drafts, await _rejected_keys(account, as_of))
    # 분할 진입(ramp) — 슬리브별 자동/수동 결정, 매수 예산만 캡(SELL 무변경).
    if profile is not None:
        from datetime import datetime

        months = resolve_ramp_months(
            int(profile.ramp_in_months or 0), strategy.universe,
            enabled_at=profile.quant_enabled_at,
        )
        cap = ramp_cap(profile.quant_enabled_at, months, now=datetime.now())
        scoped_value = sum(scoped[c] * prices.get(c, 0.0) for c in scoped)
        drafts = apply_ramp_cap(
            drafts, cap=cap, sleeve_nav=sleeve_nav, holdings_value=scoped_value,
        )
    inserted, batch_id = await _insert_proposals(
        drafts, strategy=strategy, account=account, as_of=as_of,
        market="US",
    )
    return {
        "proposal_date": as_of.isoformat(),
        "mode": "REBALANCE" if monthly_rotation else "RULES",
        "drafted": len(drafts),
        "inserted": inserted,
        "scoped_positions": len(scoped),
    }
