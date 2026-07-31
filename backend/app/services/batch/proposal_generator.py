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

SELL 초안 세금 주석(quasi-contract): ``run_proposal_generation``은 초안이
빌더에서 나온 뒤 ``_insert_proposals`` 저장 전에, side=="SELL"인 각 초안의
``reason``에 다음 4개 키를 병합한다(Flutter 제안 카드가 그대로 읽으므로 키
이름·의미는 임의 변경 금지) — ``tax_type``(``research.backtest.tax_kr.
classify_kr_instrument`` 결과: stock/etf_domestic_equity/etf_taxable/unknown),
``est_sell_tax``·``est_gains_tax``(반올림된 정수 KRW), ``tax_note``(표시용
안내문). BUY 초안에는 붙지 않는다. 순수 빌더 자체는 세금 파라미터를 모른다 —
세금 계산은 순수하게 표시용 후처리이기 때문.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update

from backend.app.core.config import settings
from backend.app.services.batch.daily_analysis import (
    latest_research_price_date,
    load_strategy,
)
from backend.app.services.kis.rest_client import KISRestClient
from research.backtest.engine import (
    _allocate_equal_weight,
    _apply_abs_momentum_gate,
    _band_trim_target,
    _score_exit_swaps,
    apply_filters,
    get_universe,
    score_stocks,
)
from research.backtest.macro_data import load_regime_series
from research.backtest.regime import compute_regime
from research.backtest.tax_kr import classify_kr_instrument, estimate_sell_tax
from shared.db.models import OrderProposal, RebalanceTarget, Setting
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
        for exit_code, replacement, percentile in _score_exit_swaps(
            ranked_codes, held, strategy.replace_if_rank_below
        ):
            qty = positions.get(exit_code, 0)
            price = prices.get(exit_code)
            if qty <= 0 or not price:
                continue
            repl_price = prices.get(replacement) if replacement else None
            if replacement and (not repl_price or repl_price <= 0):
                # 교체 종목 가격이 없으면 스왑 전체를 건너뛴다 (고아 매도 방지) —
                # 매도만 나가고 매수가 빠지면 스왑 시맨틱이 깨진다.
                continue
            exiting.add(exit_code)
            drafts.append(
                ProposalDraft(
                    exit_code, "SELL", qty, price,
                    {"rule": "SCORE_EXIT", "replacement": replacement,
                     "percentile": round(percentile, 4)},
                )
            )
            if replacement:
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
    slots: int | None = None,
) -> list[ProposalDraft]:
    """분기 앵커: 목표 동일가중 포트폴리오와 현 보유의 전체 diff (순수).

    ``slots``는 절대모멘텀 게이트(E5) 전용 — 엔진과 동일하게, 게이트로
    빠진 종목의 슬롯을 생존자에게 재분배하지 않고 현금으로 남기려면
    게이트 전 top_n(고정 분모)을 넘긴다. 기본(None)은
    ``_allocate_equal_weight``가 ``len(selected)``를 쓰는 기존 동작 그대로.
    """
    target = _allocate_equal_weight(
        selected, nav=nav, prices=prices, exposure=exposure, slots=slots
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


def ramp_cap(
    enabled_at: datetime | None, months: int, *, now: datetime
) -> float:
    """분할 진입 캡 — 퀀트 ON 후 k개월차(1-base)에 min(1, k/months).

    months<=0 또는 enabled_at 미기록(레거시 ON)이면 캡 없음(1.0).
    """
    if months <= 0 or enabled_at is None:
        return 1.0
    elapsed = (now.year - enabled_at.year) * 12 + (now.month - enabled_at.month)
    k = max(1, elapsed + 1)
    return min(1.0, k / months)


def apply_ramp_cap(
    drafts: list[ProposalDraft],
    *,
    cap: float,
    sleeve_nav: float,
    holdings_value: float,
) -> list[ProposalDraft]:
    """매수 예산을 cap×NAV − 현 보유가치로 제한 (순수).

    SELL(손절·청산 포함)은 절대 건드리지 않는다 — ramp-in은 신규 자금 투입
    속도만 늦추는 장치. BUY는 순서대로 예산에 맞춰 수량 절삭(0이면 제거).
    """
    if cap >= 1.0:
        return drafts
    budget = max(0.0, cap * sleeve_nav - holdings_value)
    out: list[ProposalDraft] = []
    for d in drafts:
        if d.side != "BUY":
            out.append(d)
            continue
        if budget <= 0 or d.last_price <= 0:
            continue
        affordable = min(d.qty, int(budget // d.last_price))
        if affordable <= 0:
            continue
        budget -= affordable * d.last_price
        out.append(
            d if affordable == d.qty
            else ProposalDraft(d.stock_code, d.side, affordable, d.last_price,
                               {**d.reason, "ramp_capped": True})
        )
    return out


def _sleeve_scope_codes(
    universe: str,
    positions: dict[str, int],
    etf_set: set[str],
    *,
    as_of: Date,
) -> set[str]:
    """보유 종목을 전략 유니버스 소속으로 스코핑 (일반/이월 경로 공용).

    DC 유니버스=allowlist ∩, ETF_KR=ETF ∩, 그 외 KR=ETF 제외 — ETF 전략이
    주식을 팔거나 그 반대 사고를 구조적으로 막는 기존 안전장치 그대로.
    """
    if universe.upper().startswith("ETF_KR_DC"):
        dc_set = set(get_universe(universe, as_of=as_of, db_path=research_db_path))
        return set(positions) & dc_set
    if universe == "ETF_KR":
        return set(positions) & etf_set
    return set(positions) - etf_set


# 위험관리 규칙 — 사용자가 거절해도 조건이 유지되면 계속 제안한다(안전 우선).
RISK_RULES = frozenset({"STOP_LOSS", "TAKE_PROFIT", "REGIME_DERISK"})


def _filter_rejected(
    drafts: list[ProposalDraft], rejected: set[tuple[str, str]]
) -> list[ProposalDraft]:
    """이번 주기에 명시적으로 거절된 (종목, 방향)은 재제안하지 않는다 (순수).

    예외: 위험관리 규칙(RISK_RULES)은 거절 이력이 있어도 통과 — 손절 조건이
    유지되는 포지션을 조용히 방치하지 않는다.
    """
    if not rejected:
        return drafts
    return [
        d for d in drafts
        if d.reason.get("rule") in RISK_RULES
        or (d.stock_code, d.side) not in rejected
    ]


async def _rejected_keys(
    account: AccountType, as_of: Date
) -> set[tuple[str, str]]:
    """이번 주기(YYYY-MM) 내 REJECTED 제안의 (종목, 방향) 집합."""
    month_start = as_of.replace(day=1)
    async with service_session() as session:
        rows = await session.execute(
            select(OrderProposal.stock_code, OrderProposal.side)
            .where(OrderProposal.status == "REJECTED")
            .where(OrderProposal.account_type == account.value)
            .where(OrderProposal.proposal_date >= month_start)
        )
    return {(row[0], row[1]) for row in rows.all()}


def build_carryover_drafts(
    target: dict[str, int],
    positions: dict[str, int],
    prices: dict[str, float],
) -> list[ProposalDraft]:
    """저장된 주기 목표 vs 현 보유의 잔여 diff → 이월 제안 (순수).

    full_rebalance_proposals와 동일 시맨틱(SELL 먼저)이되, 목표를 다시
    계산하지 않고 월초에 저장된 목표 수량을 그대로 쓴다. 가격 없는 코드는
    스킵(다음 날 재시도).
    """
    drafts: list[ProposalDraft] = []
    for code in sorted(set(positions) | set(target)):
        price = prices.get(code)
        if not price or price <= 0:
            continue
        delta = target.get(code, 0) - positions.get(code, 0)
        if delta == 0:
            continue
        side = "BUY" if delta > 0 else "SELL"
        drafts.append(
            ProposalDraft(
                code, side, abs(delta), price, {"rule": "REBALANCE_CARRYOVER"}
            )
        )
    return sorted(drafts, key=lambda d: 0 if d.side == "SELL" else 1)


def carryover_residual_notional(
    target: dict[str, int],
    positions: dict[str, int],
    prices: dict[str, float],
) -> float:
    """이월 잔여 diff의 노셔널 합 — 발동 임계(슬리브 NAV 1%) 판정용 (순수)."""
    total = 0.0
    for code in set(positions) | set(target):
        price = prices.get(code)
        if not price or price <= 0:
            continue
        total += abs(target.get(code, 0) - positions.get(code, 0)) * price
    return total


async def _save_rebalance_target(
    account: AccountType, strategy_name: str, as_of: Date, target: dict[str, int]
) -> None:
    """월초 full_rebalance의 목표 수량 맵을 (계좌, 전략, YYYY-MM)로 upsert."""
    period = as_of.strftime("%Y-%m")
    async with service_session() as session:
        row = (
            await session.execute(
                select(RebalanceTarget)
                .where(RebalanceTarget.account_type == account.value)
                .where(RebalanceTarget.strategy_name == strategy_name)
                .where(RebalanceTarget.period == period)
            )
        ).scalars().first()
        payload = json.dumps(target, ensure_ascii=False)
        if row is None:
            session.add(
                RebalanceTarget(
                    account_type=account.value,
                    strategy_name=strategy_name,
                    period=period,
                    target_json=payload,
                )
            )
        else:
            row.target_json = payload
        await session.commit()


async def load_rebalance_target(
    account: AccountType, strategy_name: str, as_of: Date
) -> dict[str, int] | None:
    """이번 주기(YYYY-MM)의 저장 목표 — 없으면 None (이월 스킵)."""
    period = as_of.strftime("%Y-%m")
    async with service_session() as session:
        row = (
            await session.execute(
                select(RebalanceTarget)
                .where(RebalanceTarget.account_type == account.value)
                .where(RebalanceTarget.strategy_name == strategy_name)
                .where(RebalanceTarget.period == period)
            )
        ).scalars().first()
    if row is None:
        return None
    try:
        loaded = json.loads(row.target_json)
        return {str(k): int(v) for k, v in loaded.items()}
    except (ValueError, AttributeError):
        return None


async def run_proposal_generation(
    *,
    strategy_name: str | None = None,
    account_type: AccountType | None = None,
    full_rebalance: bool = False,
    send_telegram: bool = True,
    nav_weight: float | None = None,
    prefetched_balance: Any | None = None,
    ramp_cap_value: float = 1.0,
) -> dict:
    """제안 생성 본체 — 브로커 보유 조회 → 슬리브 스코핑 → 규칙/전체 diff → INSERT → 텔레그램.

    슬리브 스코핑(안전장치, opt-in 파라미터 없이 항상 적용): 전략이 ``ETF_KR``
    이면 보유 중 ETF만, 그 외 전략이면 보유 중 ETF가 아닌 것만 본다. 이후
    규칙/전체 diff/노출/NAV 계산은 전부 그 슬리브 안에서만 이뤄진다 —
    ETF 전략이 주식을 팔거나 주식 전략이 ETF를 파는 사고를 구조적으로 막는다.

    ``nav_weight``/``prefetched_balance``는 :func:`run_sleeve_proposals`
    오케스트레이터가 두 슬리브를 한 번의 잔고 조회로 실행하기 위한 훅이다 —
    단독 호출(예: API의 명시적 strategy_name 경로)에서는 생략하면 된다.
    """
    strategy = load_strategy(strategy_name or settings.DEFAULT_STRATEGY_NAME)
    account = account_type or settings.PROPOSAL_ACCOUNT_TYPE
    as_of = latest_research_price_date()

    if prefetched_balance is not None:
        balance = prefetched_balance
    else:
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

    # --- 슬리브 스코핑: 보유 종목을 전략 유니버스 기준으로 분리 ---
    etf_set = set(get_universe("ETF_KR", as_of=as_of, db_path=research_db_path))
    sleeve_codes = _sleeve_scope_codes(
        strategy.universe, positions, etf_set, as_of=as_of
    )
    sleeve_positions = {code: positions[code] for code in sleeve_codes}
    sleeve_entry_prices = {code: entry_prices[code] for code in sleeve_codes}
    sleeve_holdings_value = sum(
        sleeve_positions[code] * prices.get(code, 0.0) for code in sleeve_codes
    )

    # 슬리브 NAV 비중: nav_weight가 주어지면 그대로 쓴다(오케스트레이터가 이미
    # ETF_KR용 w / 주식용 1-w를 계산해 넘긴다). 없으면(단독 호출) Setting에서
    # 읽어 스스로 계산한다.
    if nav_weight is None:
        base_weight = await _read_sleeve_weight_setting()
        weight = base_weight if strategy.universe == "ETF_KR" else (1.0 - base_weight)
    else:
        weight = nav_weight
    sleeve_nav = nav * weight

    if sleeve_nav <= 0:
        summary = {
            "proposal_date": as_of.isoformat(),
            "account": account.value,
            "strategy": strategy.name,
            "mode": "REBALANCE" if full_rebalance else "RULES",
            "drafted": 0,
            "inserted": 0,
            "skipped": True,
            "warning": (
                f"sleeve_nav<=0 (nav={nav}, weight={weight}) — sleeve skipped"
            ),
        }
        logger.warning("proposal generation skipped: %s", summary)
        return summary

    invested_exposure = min(1.0, sleeve_holdings_value / sleeve_nav)

    ranked_codes: list[str] | None = None
    selected: list[str] = []
    universe: list[str] = []
    unclassified_skipped: list[str] = []
    needs_scores = full_rebalance or strategy.replace_if_rank_below is not None
    if needs_scores:
        warnings: list[str] = []
        # ETF_KR 전략의 유니버스는 위에서 이미 조회한 etf_set과 동일하다 —
        # 같은 쿼리를 두 번 실행하지 않고 재사용한다.
        universe = (
            sorted(etf_set)
            if strategy.universe == "ETF_KR"
            else get_universe(strategy.universe, as_of=as_of, db_path=research_db_path)
        )
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
        prices.update(
            {
                c: px
                for c, px in _research_closes(
                    sorted(set(ranked_codes) - set(prices)), as_of
                ).items()
                if px > 0
            }
        )

    confirmed_exposure: float | None = None
    if strategy.use_regime:
        confirmed_exposure = _confirmed_live_exposure(as_of)

    if full_rebalance:
        # 슬리브 보유 중 전략 유니버스(및 목표 포트폴리오)에 없는 코드는
        # 분류 불가한 수동 매수로 보고 전체 diff의 매도 대상에서 제외한다 —
        # full_rebalance_proposals가 positions∪target을 순회하므로, 유니버스에
        # 없는 종목만 걸러내면 target은 그대로 매수 후보로 남는다.
        universe_set = set(universe)
        rebalance_positions = {
            code: qty for code, qty in sleeve_positions.items() if code in universe_set
        }
        unclassified_skipped = sorted(set(sleeve_positions) - universe_set)
        # 절대모멘텀 게이트(E5, engine._apply_abs_momentum_gate 재사용): 게이트
        # 대상(자기 모멘텀<=0)은 top_n에서 빠지지만, 배분 분모(slots)는 게이트
        # 전 top_n으로 고정한다 — 빠진 슬롯은 생존자에게 재분배되지 않고
        # 현금으로 남아 백테스트와 동일한 결과를 낸다.
        slots: int | None = None
        if strategy.abs_momentum_gate:
            slots = len(selected)
            selected = _apply_abs_momentum_gate(
                selected, scored,
                factor_name=strategy.abs_momentum_factor,
                as_of=as_of, db_path=research_db_path,
                warnings=warnings,
            )
        drafts = full_rebalance_proposals(
            positions=rebalance_positions, prices=prices, nav=sleeve_nav,
            selected=selected,
            exposure=confirmed_exposure if confirmed_exposure is not None else 1.0,
            slots=slots,
        )
        # 이월(carryover)용 주기 목표 저장 — 미이행분을 비월초에도 재제안 가능하게.
        target_map = _allocate_equal_weight(
            selected, nav=sleeve_nav, prices=prices,
            exposure=confirmed_exposure if confirmed_exposure is not None else 1.0,
            slots=slots,
        )
        await _save_rebalance_target(account, strategy.name, as_of, target_map)
    else:
        drafts = build_rule_proposals(
            strategy=strategy, positions=sleeve_positions,
            entry_prices=sleeve_entry_prices, prices=prices, nav=sleeve_nav,
            ranked_codes=ranked_codes,
            invested_exposure=invested_exposure,
            confirmed_regime_exposure=confirmed_exposure,
        )
    drafts = [d for d in drafts if d.qty > 0 and d.last_price > 0]
    # 거절 존중: 이번 주기 내 명시적 거절 (종목, 방향)은 재제안 억제(위험규칙 예외).
    drafts = _filter_rejected(drafts, await _rejected_keys(account, as_of))
    # 분할 진입(ramp-in): 매수 예산을 cap×NAV로 제한 (SELL 무변경).
    drafts = apply_ramp_cap(
        drafts, cap=ramp_cap_value, sleeve_nav=sleeve_nav,
        holdings_value=sleeve_holdings_value,
    )
    for draft in drafts:
        if draft.side != "SELL":
            continue
        is_etf = draft.stock_code in etf_set
        entry = entry_prices.get(draft.stock_code) or 0.0
        classification = classify_kr_instrument(draft.stock_code, is_etf=is_etf)
        tax = estimate_sell_tax(
            draft.stock_code, draft.qty, draft.last_price, entry,
            classification=classification,
        )
        if classification == "etf_taxable" and not entry:
            # 매입단가 미확인 — 차익을 추정하면 (매도가-0)*수량을 전부 차익으로
            # 오인해 세금을 크게 과대추정하게 된다. 절대 추측하지 않고 0으로
            # 표시한다(안내문은 그대로 유지).
            tax = {**tax, "est_gains_tax": 0.0}
        draft.reason.update(
            {
                "tax_type": tax["tax_type"],
                "est_sell_tax": round(tax["est_sell_tax"]),
                "est_gains_tax": round(tax["est_gains_tax"]),
                "tax_note": tax["tax_note"],
            }
        )

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
        "buy_notional": round(
            sum(d.estimated_notional for d in drafts if d.side == "BUY"), 2
        ),
    }
    if unclassified_skipped:
        summary["unclassified_skipped"] = unclassified_skipped
    logger.info("proposal generation %s", summary)
    if send_telegram and inserted:
        await _notify(drafts, summary)
    return summary


async def run_carryover_generation(
    *,
    strategy_name: str,
    account_type: AccountType,
    nav_weight: float,
    send_telegram: bool = True,
    ramp_cap_value: float = 1.0,
) -> dict:
    """비월초 이월 재제안 — 이번 주기 저장 목표 vs 실보유의 잔여 diff.

    잔여 노셔널이 슬리브 NAV의 1% 미만이면 이행 완료로 보고 스킵한다.
    거절 존중 필터 동일 적용.
    """
    strategy = load_strategy(strategy_name)
    account = account_type
    as_of = latest_research_price_date()

    target = await load_rebalance_target(account, strategy.name, as_of)
    if not target:
        return {"skipped": "no saved target this period"}

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
    sleeve_nav = nav * nav_weight

    etf_set = set(get_universe("ETF_KR", as_of=as_of, db_path=research_db_path))
    sleeve_codes = _sleeve_scope_codes(
        strategy.universe, positions, etf_set, as_of=as_of
    )
    scoped = {code: positions[code] for code in sleeve_codes}
    # 목표 종목의 가격 공백은 연구 종가로 보강 (보유에 없는 매수 대상)
    missing = sorted(set(target) - set(prices))
    prices = {**prices, **_research_closes(missing, as_of)}

    residual = carryover_residual_notional(target, scoped, prices)
    if residual < sleeve_nav * 0.01:
        return {"skipped": f"carryover residual below 1% ({residual:.0f})"}

    drafts = build_carryover_drafts(target, scoped, prices)
    drafts = [d for d in drafts if d.qty > 0 and d.last_price > 0]
    drafts = _filter_rejected(drafts, await _rejected_keys(account, as_of))
    scoped_value = sum(scoped[c] * prices.get(c, 0.0) for c in scoped)
    drafts = apply_ramp_cap(
        drafts, cap=ramp_cap_value, sleeve_nav=sleeve_nav,
        holdings_value=scoped_value,
    )
    inserted = await _insert_proposals(
        drafts, strategy=strategy, account=account, as_of=as_of,
    )
    summary = {
        "proposal_date": as_of.isoformat(),
        "account": account.value,
        "strategy": strategy.name,
        "mode": "CARRYOVER",
        "drafted": len(drafts),
        "inserted": inserted,
        "residual": round(residual),
    }
    logger.info("carryover generation %s", summary)
    if send_telegram and inserted:
        await _notify(drafts, summary)
    return summary


async def run_sleeve_proposals(
    *,
    account_type: AccountType | None = None,
    send_telegram: bool = True,
) -> dict:
    """2-슬리브(주식/ETF) 오케스트레이터 — KIS 잔고 1회 조회를 양쪽에 재사용.

    주식 슬리브는 매일 규칙(daily rules) 모드로 실행되고, ETF 슬리브는
    월초 첫 거래일에만 분기 앵커(full_rebalance) 모드로 실행된다. 한쪽
    슬리브가 실패해도(예: private 전략 파일 누락) 다른 슬리브는 계속
    실행된다 — 최종 안전장치는 승인 게이트 + 브로커 거부이므로, 여기서는
    경고만 남기고 제안 자체를 막지는 않는다.
    """
    account = account_type or settings.PROPOSAL_ACCOUNT_TYPE
    as_of = latest_research_price_date()
    stock_name, etf_name, weight = await _read_sleeve_settings()

    client = KISRestClient()
    balance = await client.get_balance(account)

    warnings: list[str] = []
    sleeves: dict[str, dict] = {}

    sleeves["stock"] = await _run_sleeve_safe(
        "stock",
        strategy_name=stock_name,
        account=account,
        full_rebalance=False,
        nav_weight=1.0 - weight,
        prefetched_balance=balance,
        send_telegram=send_telegram,
        warnings=warnings,
    )

    if _is_month_start(as_of):
        sleeves["etf"] = await _run_sleeve_safe(
            "etf",
            strategy_name=etf_name,
            account=account,
            full_rebalance=True,
            nav_weight=weight,
            prefetched_balance=balance,
            send_telegram=send_telegram,
            warnings=warnings,
        )
    else:
        # 월초가 아니어도 이번 달 목표의 미이행분이 남아 있으면 이월 재제안.
        try:
            sleeves["etf"] = await run_carryover_generation(
                strategy_name=etf_name,
                account_type=account,
                nav_weight=weight,
                send_telegram=send_telegram,
            )
        except Exception as exc:  # noqa: BLE001 — 이월 실패가 주식 슬리브를 막지 않게
            logger.exception("etf sleeve carryover failed")
            warnings.append(f"etf carryover failed: {exc}")
            sleeves["etf"] = {"error": "carryover failed (see logs)"}

    account_nav, account_holdings_value = _account_nav_and_holdings(balance)
    est_cash = account_nav - account_holdings_value
    total_buy_notional = sum(
        sleeve.get("buy_notional", 0.0) for sleeve in sleeves.values()
    )
    if total_buy_notional > est_cash:
        warnings.append(
            f"cash over-commit: buys≈{total_buy_notional:.0f} > "
            f"est_cash≈{est_cash:.0f}"
        )

    summary = {"as_of": as_of.isoformat(), "sleeves": sleeves, "warnings": warnings}
    logger.info("sleeve proposal generation %s", summary)
    return summary


async def _run_sleeve_safe(
    label: str,
    *,
    strategy_name: str,
    account: AccountType,
    full_rebalance: bool,
    nav_weight: float,
    prefetched_balance: Any,
    send_telegram: bool,
    warnings: list[str],
) -> dict:
    """한 슬리브를 실행하고, 실패해도 다른 슬리브를 막지 않도록 예외를 가둔다."""
    try:
        return await run_proposal_generation(
            strategy_name=strategy_name,
            account_type=account,
            full_rebalance=full_rebalance,
            send_telegram=send_telegram,
            nav_weight=nav_weight,
            prefetched_balance=prefetched_balance,
        )
    except FileNotFoundError as exc:
        logger.warning("sleeve %s skipped: strategy file missing (%s)", label, exc)
        warnings.append(f"{label} sleeve: strategy file missing ({exc})")
        return {"error": f"strategy file missing: {exc}"}
    except Exception as exc:  # noqa: BLE001 — 한쪽 슬리브 실패가 다른 슬리브를 막으면 안 됨
        logger.exception("sleeve %s failed", label)
        warnings.append(f"{label} sleeve failed: {exc}")
        return {"error": "sleeve generation failed (see logs)"}


def _parse_sleeve_weight(raw: str | None) -> float:
    """ETF 슬리브 비중 문자열 파싱 — backend.app.api.settings.parse_sleeve_weight와
    동일한 로직의 인라인 재구현이다(batch 계층은 api 계층을 import하지 않는다).
    파싱 실패 시 settings.DEFAULT_SLEEVE_ETF_WEIGHT로 폴백하고 [0.0, 1.0]로 clamp.
    """
    try:
        value = float(raw) if raw is not None else settings.DEFAULT_SLEEVE_ETF_WEIGHT
    except (TypeError, ValueError):
        value = settings.DEFAULT_SLEEVE_ETF_WEIGHT
    return max(0.0, min(1.0, value))


async def _read_sleeve_weight_setting() -> float:
    async with service_session() as session:
        row = await session.get(Setting, "sleeve_etf_weight")
    return _parse_sleeve_weight(row.value if row is not None else None)


async def _read_sleeve_settings() -> tuple[str, str, float]:
    """(주식 전략명, ETF 전략명, ETF 비중) — Setting 조회 + 기본값 폴백."""
    async with service_session() as session:
        rows = {
            row.key: row.value
            for row in (await session.execute(select(Setting))).scalars()
        }
    stock_name = rows.get("rating_strategy_name") or settings.DEFAULT_STRATEGY_NAME
    etf_name = rows.get("etf_strategy_name") or settings.DEFAULT_ETF_STRATEGY_NAME
    weight = _parse_sleeve_weight(rows.get("sleeve_etf_weight"))
    return stock_name, etf_name, weight


def _account_nav_and_holdings(balance: Any) -> tuple[float, float]:
    """계좌 전체(잔고) NAV·평가금액 — run_proposal_generation의 계좌 루프와 동일 계산."""
    holdings_value = 0.0
    for pos in balance.positions:
        qty = int(pos.quantity)
        if qty <= 0:
            continue
        price = float(pos.current_price or pos.avg_buy_price or 0)
        holdings_value += qty * price
    nav = float(balance.summary.total_evaluation_amount or 0) or (
        holdings_value or 1.0
    )
    return nav, holdings_value


def _is_month_start(as_of: Date) -> bool:
    """as_of 이전 최신 거래일이 전월(또는 전년)이면 월초 첫 거래일로 판단한다."""
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM prices_daily WHERE date < ?",
            (as_of.isoformat(),),
        ).fetchone()
    prev_raw = row[0] if row else None
    if prev_raw is None:
        return True
    prev = Date.fromisoformat(str(prev_raw))
    return prev.year != as_of.year or prev.month != as_of.month


def _research_closes(codes: list[str], as_of: Date) -> dict[str, float]:
    """연구DB(prices_daily)에서 as_of 이하 최신 종가로 가격 공백을 보강.

    코드별 ``COALESCE(adj_close, close)`` 최신값(``date <= as_of``)을 반환.
    데이터가 없는 코드는 결과에서 빠진다 — 호출부의 기존 price>0 가드가
    자연스럽게 걸러낸다(더 이상 0.0으로 조용히 채우지 않는다).
    """
    if not codes:
        return {}
    placeholders = ",".join("?" * len(codes))
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT stock_code, COALESCE(adj_close, close) AS px
            FROM prices_daily
            WHERE stock_code IN ({placeholders}) AND date <= ?
            ORDER BY stock_code, date
            """,
            (*codes, as_of.isoformat()),
        ).fetchall()
    latest: dict[str, float] = {}
    for code, px in rows:
        if px is not None:
            latest[code] = float(px)  # date ASC — last row per code wins
    return latest


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
    strategy: StrategyDefinition | None = None,
    account: AccountType,
    as_of: Date,
    strategy_name: str | None = None,
    market: str = "KR",
) -> int:
    """제안 저장 — strategy 없이 표시용 이름만으로도 저장 가능(hold 슬리브),
    market 파라미터로 US 제안(Toss) 지원. 기존 콜사이트는 무변경."""
    if not drafts:
        return 0
    name = strategy_name or (strategy.name if strategy else None)
    if not name:
        raise ValueError("strategy or strategy_name is required")
    batch_id = uuid.uuid4().hex
    config_hash = (
        hashlib.sha1(strategy.model_dump_json().encode("utf-8")).hexdigest()[:10]
        if strategy is not None
        else None
    )
    expires_at = _next_business_morning(as_of)
    inserted = 0
    async with service_session() as session:
        pending = await session.execute(
            select(OrderProposal.stock_code, OrderProposal.side).where(
                OrderProposal.status == "PROPOSED"
            ).where(
                OrderProposal.strategy_name == name
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
                    strategy_name=name,
                    config_hash=config_hash,
                    stock_code=draft.stock_code,
                    market=market,
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
