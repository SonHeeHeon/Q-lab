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
from backend.app.services.batch.account_proposals import scope_us_positions
from backend.app.services.batch.proposal_generator import (
    _insert_proposals,
    _is_month_start,
    _research_closes,
    build_rule_proposals,
    full_rebalance_proposals,
)
from backend.app.services.toss.rest_client import TossRestClient
from research.backtest.engine import (
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
            )
        except Exception as exc:  # noqa: BLE001 — 슬리브 실패 격리
            logger.exception("toss sleeve %s failed", name)
            results[name] = {"error": str(exc)}
    return results


async def _run_one_sleeve(
    name: str, weight: float, *, as_of, nav: float,
    positions: dict[str, int], entry_prices: dict[str, float],
    prices: dict[str, float],
) -> dict:
    strategy = load_strategy(name)
    universe = get_universe(strategy.universe, as_of=as_of, db_path=research_db_path)
    universe_set = set(universe)
    scoped = scope_us_positions(positions, universe_set)
    sleeve_nav = nav * weight
    monthly_rotation = strategy.rebalance_freq == "MONTHLY"

    if monthly_rotation and not _is_month_start(as_of):
        return {"skipped": "not month start"}

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
    else:
        drafts = build_rule_proposals(
            strategy=strategy, positions=scoped, entry_prices=entry_prices,
            prices=prices, nav=sleeve_nav,
        )

    drafts = [d for d in drafts if d.qty > 0 and d.last_price > 0]
    inserted, batch_id = await _insert_proposals(
        drafts, strategy=strategy, account=AccountType.REAL, as_of=as_of,
        market="US",
    )
    return {
        "proposal_date": as_of.isoformat(),
        "mode": "REBALANCE" if monthly_rotation else "RULES",
        "drafted": len(drafts),
        "inserted": inserted,
        "scoped_positions": len(scoped),
    }
