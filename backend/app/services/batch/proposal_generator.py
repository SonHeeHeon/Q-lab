"""승인형 반자동 — 일일 주문 제안 생성/만료 배치.

전략(기본: private 우선 해석)과 현재 KIS 보유를 비교해 order_proposals에
제안을 쌓는다. 실행은 하지 않는다 — 사용자가 앱에서 승인해야 주문 API
(안전 게이트웨이·멱등키 경유)로 넘어간다.

일일 모드(rule 기반): 전략 YAML에 켜져 있는 검증된 규칙만 발동
  STOP_LOSS / TAKE_PROFIT (브로커 평단 기준) · BAND_TRIM · SCORE_EXIT ·
  REGIME_DERISK (확정 레짐 노출 < 현재 투자비중)
분기 앵커 모드(full_rebalance=True): 목표 동일가중 포트폴리오와의 전체 diff.

순수 빌더(build_rule_proposals/full_rebalance_proposals)는 DB/브로커 없이
테스트되고, 엔진의 규칙 헬퍼(_band_trim_target/_score_exit_swaps)를 그대로
재사용해 백테스트와 라이브 제안이 같은 논리로 움직인다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select, update

from backend.app.core.config import settings
from backend.app.services.batch.daily_analysis import (
    latest_research_price_date,
    load_strategy,
)
from backend.app.services.kis.rest_client import KISRestClient
from research.backtest.engine import (
    _allocate_equal_weight,
    _band_trim_target,
    _score_exit_swaps,
    apply_filters,
    get_universe,
    score_stocks,
)
from research.backtest.macro_data import load_regime_series
from research.backtest.regime import compute_regime
from shared.db.models import OrderProposal
from shared.db.session import research_db_path, service_session
from shared.domain.account import AccountType
from shared.domain.strategy import StrategyDefinition

logger = logging.getLogger(__name__)

BUY_LIMIT_RATIO = 0.997
SELL_LIMIT_RATIO = 1.003
SWAP_BUDGET_HAIRCUT = 0.99  # engine SCORE_EXIT와 동일 (왕복비용 여유)


@dataclass(slots=True)
class ProposalDraft:
    stock_code: str
    side: str  # BUY | SELL
    qty: int
    last_price: float
    reason: dict = field(default_factory=dict)

    @property
    def limit_price(self) -> float:
        ratio = BUY_LIMIT_RATIO if self.side == "BUY" else SELL_LIMIT_RATIO
        return round(self.last_price * ratio, 2)

    @property
    def estimated_notional(self) -> float:
        return round(self.qty * self.last_price, 2)


def build_rule_proposals(
    *,
    strategy: StrategyDefinition,
    positions: dict[str, int],
    entry_prices: dict[str, float],
    prices: dict[str, float],
    nav: float,
    ranked_codes: list[str] | None = None,
    invested_exposure: float = 1.0,
    confirmed_regime_exposure: float | None = None,
) -> list[ProposalDraft]:
    """전략에 켜진 중간매매 규칙만으로 제안 목록 생성 (순수 함수).

    규칙 우선순위: 전량 청산(STOP/TP) → SCORE_EXIT 스왑 → BAND_TRIM →
    REGIME_DERISK. 이미 전량 청산 대상인 종목은 후순위 규칙에서 제외.
    """
    drafts: list[ProposalDraft] = []
    exiting: set[str] = set()

    if strategy.stop_loss_pct is not None or strategy.take_profit_pct is not None:
        for code, qty in positions.items():
            entry = entry_prices.get(code)
            price = prices.get(code)
            if not entry or not price or entry <= 0 or qty <= 0:
                continue
            position_return = price / entry - 1.0
            rule = None
            if (
                strategy.stop_loss_pct is not None
                and position_return <= strategy.stop_loss_pct
            ):
                rule = "STOP_LOSS"
            elif (
                strategy.take_profit_pct is not None
                and position_return >= strategy.take_profit_pct
            ):
                rule = "TAKE_PROFIT"
            if rule:
                exiting.add(code)
                drafts.append(
                    ProposalDraft(
                        code, "SELL", qty, price,
                        {"rule": rule, "return": round(position_return, 4),
                         "entry": entry},
                    )
                )

    if strategy.replace_if_rank_below is not None and ranked_codes:
        held = {c for c in positions if c not in exiting}
        for exit_code, replacement in _score_exit_swaps(
            ranked_codes, held, strategy.replace_if_rank_below
        ):
            qty = positions.get(exit_code, 0)
            price = prices.get(exit_code)
            if qty <= 0 or not price:
                continue
            exiting.add(exit_code)
            drafts.append(
                ProposalDraft(
                    exit_code, "SELL", qty, price,
                    {"rule": "SCORE_EXIT", "replacement": replacement},
                )
            )
            if replacement:
                repl_price = prices.get(replacement)
                if repl_price and repl_price > 0:
                    budget = qty * price * SWAP_BUDGET_HAIRCUT
                    repl_qty = int(budget // repl_price)
                    if repl_qty > 0:
                        drafts.append(
                            ProposalDraft(
                                replacement, "BUY", repl_qty, repl_price,
                                {"rule": "SCORE_EXIT", "replaces": exit_code},
                            )
                        )

    if strategy.band_trim_threshold is not None:
        remaining = {c: q for c, q in positions.items() if c not in exiting}
        target = _band_trim_target(
            remaining, prices, nav=nav,
            exposure=invested_exposure,
            threshold=strategy.band_trim_threshold,
        )
        if target:
            for code, target_qty in target.items():
                current_qty = remaining.get(code, 0)
                price = prices.get(code)
                if target_qty < current_qty and price:
                    drafts.append(
                        ProposalDraft(
                            code, "SELL", current_qty - target_qty, price,
                            {"rule": "BAND_TRIM", "target_qty": target_qty},
                        )
                    )

    if (
        strategy.use_regime
        and confirmed_regime_exposure is not None
        and invested_exposure > 0
        and confirmed_regime_exposure < invested_exposure
    ):
        ratio = confirmed_regime_exposure / invested_exposure
        for code, qty in positions.items():
            if code in exiting:
                continue
            price = prices.get(code)
            sell_qty = qty - int(qty * ratio)
            if sell_qty > 0 and price:
                drafts.append(
                    ProposalDraft(
                        code, "SELL", sell_qty, price,
                        {"rule": "REGIME_DERISK",
                         "exposure": confirmed_regime_exposure},
                    )
                )

    return drafts


def full_rebalance_proposals(
    *,
    positions: dict[str, int],
    prices: dict[str, float],
    nav: float,
    selected: list[str],
    exposure: float = 1.0,
) -> list[ProposalDraft]:
    """분기 앵커: 목표 동일가중 포트폴리오와 현 보유의 전체 diff (순수)."""
    target = _allocate_equal_weight(
        selected, nav=nav, prices=prices, exposure=exposure
    )
    drafts: list[ProposalDraft] = []
    for code in sorted(set(positions) | set(target)):
        price = prices.get(code)
        if not price:
            continue
        delta = target.get(code, 0) - positions.get(code, 0)
        if delta > 0:
            drafts.append(
                ProposalDraft(code, "BUY", delta, price, {"rule": "REBALANCE"})
            )
        elif delta < 0:
            drafts.append(
                ProposalDraft(code, "SELL", -delta, price, {"rule": "REBALANCE"})
            )
    # 매도 먼저(현금 확보) — 승인 화면 정렬에도 쓰임
    return sorted(drafts, key=lambda d: 0 if d.side == "SELL" else 1)


async def run_proposal_generation(
    *,
    strategy_name: str | None = None,
    account_type: AccountType | None = None,
    full_rebalance: bool = False,
    send_telegram: bool = True,
) -> dict:
    """제안 생성 본체 — 브로커 보유 조회 → 규칙/전체 diff → INSERT → 텔레그램."""
    strategy = load_strategy(strategy_name or settings.DEFAULT_STRATEGY_NAME)
    account = account_type or settings.PROPOSAL_ACCOUNT_TYPE
    as_of = latest_research_price_date()

    client = KISRestClient()
    balance = await client.get_balance(account)
    positions: dict[str, int] = {}
    entry_prices: dict[str, float] = {}
    prices: dict[str, float] = {}
    holdings_value = 0.0
    for pos in balance.positions:
        code = pos.stock_code.zfill(6)
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
    invested_exposure = min(1.0, holdings_value / nav) if nav > 0 else 0.0

    ranked_codes: list[str] | None = None
    selected: list[str] = []
    needs_scores = full_rebalance or strategy.replace_if_rank_below is not None
    if needs_scores:
        warnings: list[str] = []
        universe = get_universe(strategy.universe, as_of=as_of, db_path=research_db_path)
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
        ranked_codes = [str(c) for c in scored.index]
        selected = ranked_codes[: strategy.top_n]
        # 스코어 대상 종목의 연구 종가로 가격 공백 보강
        for code in set(ranked_codes) - set(prices):
            prices.setdefault(code, 0.0)

    confirmed_exposure: float | None = None
    if strategy.use_regime:
        confirmed_exposure = _confirmed_live_exposure(as_of)

    if full_rebalance:
        drafts = full_rebalance_proposals(
            positions=positions, prices=prices, nav=nav,
            selected=selected,
            exposure=confirmed_exposure if confirmed_exposure is not None else 1.0,
        )
    else:
        drafts = build_rule_proposals(
            strategy=strategy, positions=positions,
            entry_prices=entry_prices, prices=prices, nav=nav,
            ranked_codes=ranked_codes,
            invested_exposure=invested_exposure,
            confirmed_regime_exposure=confirmed_exposure,
        )
    drafts = [d for d in drafts if d.qty > 0 and d.last_price > 0]

    inserted = await _insert_proposals(
        drafts, strategy=strategy, account=account, as_of=as_of,
    )
    summary = {
        "proposal_date": as_of.isoformat(),
        "account": account.value,
        "strategy": strategy.name,
        "mode": "REBALANCE" if full_rebalance else "RULES",
        "drafted": len(drafts),
        "inserted": inserted,
    }
    logger.info("proposal generation %s", summary)
    if send_telegram and inserted:
        await _notify(drafts, summary)
    return summary


def _confirmed_live_exposure(as_of: Date, persistence: int = 5) -> float | None:
    """최근 ``persistence`` 영업일 라벨이 모두 같을 때만 확정 노출 반환."""
    series = load_regime_series(as_of, db_path=research_db_path)
    if not series:
        return None
    states = [
        compute_regime(as_of - timedelta(days=offset), **series)
        for offset in range(persistence)
    ]
    label = states[0].label
    if all(state.label == label for state in states):
        return states[0].exposure
    return None


async def _insert_proposals(
    drafts: list[ProposalDraft],
    *,
    strategy: StrategyDefinition,
    account: AccountType,
    as_of: Date,
) -> int:
    if not drafts:
        return 0
    batch_id = uuid.uuid4().hex
    config_hash = hashlib.sha1(
        strategy.model_dump_json().encode("utf-8")
    ).hexdigest()[:10]
    expires_at = _next_business_morning(as_of)
    inserted = 0
    async with service_session() as session:
        pending = await session.execute(
            select(OrderProposal.stock_code, OrderProposal.side).where(
                OrderProposal.status == "PROPOSED"
            )
        )
        already = {(row[0], row[1]) for row in pending.all()}
        for draft in drafts:
            if (draft.stock_code, draft.side) in already:
                continue  # 같은 방향 제안이 이미 대기 중 — 중복 금지
            session.add(
                OrderProposal(
                    batch_id=batch_id,
                    proposal_date=as_of,
                    account_type=account.value,
                    strategy_name=strategy.name,
                    config_hash=config_hash,
                    stock_code=draft.stock_code,
                    market="KR",
                    side=draft.side,
                    qty=draft.qty,
                    order_type="LIMIT",
                    limit_price=Decimal(str(draft.limit_price)),
                    last_price=Decimal(str(draft.last_price)),
                    estimated_notional=Decimal(str(draft.estimated_notional)),
                    reason_json=json.dumps(draft.reason, ensure_ascii=False),
                    status="PROPOSED",
                    expires_at=expires_at,
                )
            )
            inserted += 1
        await session.commit()
    return inserted


def _next_business_morning(as_of: Date) -> datetime:
    """다음 영업일 08:30 — 미승인 제안의 만료 시각."""
    day = as_of + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, time(8, 30))


async def run_proposal_expiry() -> int:
    """만료 시각이 지난 PROPOSED 제안을 EXPIRED로 정리."""
    now = datetime.now()
    async with service_session() as session:
        result = await session.execute(
            update(OrderProposal)
            .where(OrderProposal.status == "PROPOSED")
            .where(OrderProposal.expires_at.is_not(None))
            .where(OrderProposal.expires_at < now)
            .values(status="EXPIRED", updated_at=now)
        )
        await session.commit()
    expired = int(result.rowcount or 0)
    if expired:
        logger.info("proposal expiry: %s rows", expired)
    return expired


async def _notify(drafts: list[ProposalDraft], summary: dict) -> None:
    try:
        from backend.app.services.notify.telegram import send_markdown

        sells = [d for d in drafts if d.side == "SELL"]
        buys = [d for d in drafts if d.side == "BUY"]
        lines = [
            f"*오늘의 매매 제안* ({summary['proposal_date']}, {summary['mode']})",
            f"전략 {summary['strategy']} · 계좌 {summary['account']}",
            f"매도 {len(sells)}건 / 매수 {len(buys)}건 — 앱에서 승인 필요",
        ]
        for draft in drafts[:10]:
            rule = draft.reason.get("rule", "")
            lines.append(
                f"· {draft.side} {draft.stock_code} ×{draft.qty} ({rule})"
            )
        if len(drafts) > 10:
            lines.append(f"· … 외 {len(drafts) - 10}건")
        await send_markdown("\n".join(lines))
    except Exception:
        logger.exception("proposal telegram notify failed")
