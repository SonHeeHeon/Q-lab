"""매도축 등급 규칙 엔진 — 순수 함수, DB/브로커 의존 없음 (Phase T3).

보유 종목 하나(:class:`PositionContext`)를 규칙 우선순위에 따라 5단계로
평가한다: SELL_NOW(즉시매도) > SELL(매도) > WATCH(관망) > HOLD(보유) >
KEEP(유지) 순으로 심각도가 높다(SELL_NOW가 가장 급함). 등급/사유는 전부
로직 기반(비-LLM) 표시·참고용이며 자동 주문과 직접 연결되지 않는다
(``ratings/__init__.py`` 참고).

규칙 우선순위 (첫 매치 우선, 단 BAND_TRIM은 별도의 상한 CAP):

1. STOP_LOSS — ``pl_rate``(브로커 평가손익률, %) <= ``stop_loss_pct`` →
   SELL_NOW. percentile 유무와 무관하게 항상 먼저 확인한다(NO_DATA보다
   우선).
2. TAKE_PROFIT — ``strategy.take_profit_pct`` 가 설정된 경우
   ``pl_rate >= take_profit_pct * 100`` → SELL. **단위 정규화**:
   ``strategy.take_profit_pct`` 는 분수 표현(0.30 = +30%)이다 —
   ``proposal_generator.build_rule_proposals`` 의
   ``position_return = price / entry - 1.0``(분수, backend/app/services/
   batch/proposal_generator.py:101-112)와 같은 축의 값이며, 브로커
   ``pl_rate``(%)와는 축이 다르므로 100을 곱해 정규화한 뒤 비교한다.
   현재 배포된 전략 YAML에는 ``take_profit_pct`` 가 설정된 것이 없어(모두
   None) 이 티어는 사실상 비활성(inert)이다 — 향후 전략에 값이 채워지면
   자동으로 활성화된다.
3/5. SCORE_PERCENTILE — ``percentile``(1.0 = 최고) 구간별:
   p < 0.2 → SELL, 0.2 <= p < 0.4 → WATCH, 0.4 <= p < 0.6 → HOLD,
   p >= 0.6 → KEEP.
4. BAND_TRIM (CAP) — ``strategy.band_trim_threshold`` 가 설정되어 있고
   ``in_universe`` 이며 ``position_value``/``nav``/``holding_count`` 가
   모두 주어졌을 때, 현재 비중이 ``base_weight * threshold`` 를 넘으면
   등급을 WATCH로 상한(cap)한다. 이미 그보다 엄격한 등급(SELL_NOW/SELL)
   이거나 이미 WATCH 이하이면 변화 없음 — 즉 이 CAP은 그 결과가 HOLD 또는
   KEEP일 때만 WATCH로 낮춘다(어느 티어에서 HOLD/KEEP이 나왔는지는
   가리지 않는다 — NO_DATA로 인한 HOLD도 동일하게 취급, 과다비중
   위험은 사유와 무관하기 때문). 공식은
   ``research/backtest/engine.py:960-988`` (``_band_trim_target``)과
   ``INVESTABLE_NAV_RATIO``(engine.py:59, = 0.995)를 그대로 복사했다.
   ``exposure`` 값은 이 컨텍스트에 없으므로
   ``build_rule_proposals`` 의 기본값(1.0, 풀 노출)과 동일하게 가정한다.
6. NO_DATA — ``percentile`` 이 없을 때(미국 종목이거나 KR NO_DATA/
   UNSUPPORTED) → HOLD, ``{"rule": "NO_DATA"}`` (+ ``{"note": "US"}``
   when ``is_us``). STOP_LOSS(1번)는 이보다 우선한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from research.backtest.engine import INVESTABLE_NAV_RATIO
from shared.domain.strategy import StrategyDefinition

# build_rule_proposals(invested_exposure=1.0 기본값)과 동일 — 포지션
# 컨텍스트에는 레짐 축소 노출값이 없으므로 풀 노출(1.0)을 가정한다.
_BAND_TRIM_EXPOSURE = 1.0


@dataclass(frozen=True)
class PositionContext:
    code: str
    pl_rate: float | None  # 손익률 %, e.g. -12.3 (브로커 unrealized_pl_rate)
    percentile: float | None  # 매수축 백분위, NO_DATA/UNSUPPORTED면 None
    weakest_group: str | None
    position_value: float | None  # 평가금액 (band-trim용)
    nav: float | None  # 계좌 NAV
    holding_count: int | None  # band-trim 균등가중 분모 (계좌 보유 종목 수)
    in_universe: bool
    is_us: bool


def _band_trim_cap(ctx: PositionContext, strategy: StrategyDefinition) -> dict | None:
    """band-trim 과다비중 여부. 미설정/데이터 부족/미과다면 None."""
    if strategy.band_trim_threshold is None or not ctx.in_universe:
        return None
    if ctx.position_value is None or ctx.nav is None or ctx.holding_count is None:
        return None
    if ctx.nav <= 0 or ctx.holding_count <= 0:
        return None
    base_weight = _BAND_TRIM_EXPOSURE * INVESTABLE_NAV_RATIO / ctx.holding_count
    weight = ctx.position_value / ctx.nav
    if weight <= base_weight * strategy.band_trim_threshold:
        return None
    return {
        "rule": "BAND_TRIM",
        "weight": round(weight, 4),
        "target": round(base_weight, 4),
    }


def rate_position(
    ctx: PositionContext, strategy: StrategyDefinition, *, stop_loss_pct: float
) -> tuple[str, dict]:
    """포지션 하나를 매도축 5등급으로 평가한다 (순수 함수). reason은 항상 비어있지 않다."""

    # Tier 1: STOP_LOSS — percentile 유무와 무관하게 최우선.
    if ctx.pl_rate is not None and ctx.pl_rate <= stop_loss_pct:
        return "SELL_NOW", {
            "rule": "STOP_LOSS",
            "pl_rate": ctx.pl_rate,
            "threshold": stop_loss_pct,
        }

    # Tier 2: TAKE_PROFIT (배포 전략에는 비활성 — 모듈 docstring 참고)
    if (
        strategy.take_profit_pct is not None
        and ctx.pl_rate is not None
        and ctx.pl_rate >= strategy.take_profit_pct * 100
    ):
        return "SELL", {
            "rule": "TAKE_PROFIT",
            "pl_rate": ctx.pl_rate,
            "threshold": strategy.take_profit_pct * 100,
        }

    # Tier 3/5: SCORE_PERCENTILE, Tier 6: NO_DATA
    if ctx.percentile is not None:
        p = ctx.percentile
        reason: dict = {"rule": "SCORE_PERCENTILE", "percentile": p}
        if ctx.weakest_group is not None:
            reason["weakest_group"] = ctx.weakest_group
        if p < 0.2:
            grade = "SELL"
        elif p < 0.4:
            grade = "WATCH"
        elif p < 0.6:
            grade = "HOLD"
        else:
            grade = "KEEP"
    else:
        grade = "HOLD"
        reason = {"rule": "NO_DATA"}
        if ctx.is_us:
            reason["note"] = "US"

    # Tier 4: BAND_TRIM — HOLD/KEEP만 WATCH로 상한. SELL_NOW/SELL/WATCH는 유지.
    if grade in ("HOLD", "KEEP"):
        band_trim = _band_trim_cap(ctx, strategy)
        if band_trim is not None:
            return "WATCH", band_trim

    return grade, reason
