"""US 자문 슬리브 — US 퀀트 방정식(us_value 등)으로 US_LARGE를 랭킹해 '오늘의
목표 포트폴리오'를 제시하고, Toss 보유와 비교해 BUY/SELL/HOLD 자문을 만든다.

⚠️ 자문 전용: Toss 라이브 주문이 미연동이므로 실주문·OrderProposal INSERT·텔레그램
주문을 하지 않는다. 순수 표시용 제안이다(KIS 실행 파이프라인과 완전 분리).
"""

from __future__ import annotations

import sqlite3
from datetime import date

from backend.app.services.batch.daily_analysis import load_strategy
from research.backtest.engine import get_universe, score_stocks
from shared.db.session import research_db_path

# 공개 기본 방정식. 튜닝판(us_value/us_momentum/us_multifactor)은 private/ 전용이라
# 오픈소스 클론에는 없다 — 기본값은 항상 공개 파일이어야 한다(safe default).
DEFAULT_US_STRATEGY = "us_stock_v1"


def _latest_us_price_date(db_path: str) -> date | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM prices_daily_us"
        ).fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


_target_cache: dict[tuple[str, str, int], list[str]] = {}


def _ranked_target(strategy, strategy_name: str, universe, as_of, n: int) -> list[str]:
    """전략 상위 N 티커. ~515종목 멀티팩터 스코어링이 요청당 8초 가까이 걸려
    프론트 타임아웃(8s)에 걸렸다. 같은 (거래일, 전략, N)이면 결과가 동일하므로
    캐시한다 — 보유 대비 diff는 캐시하지 않아 잔고 변화는 즉시 반영된다."""
    key = (as_of.isoformat(), strategy_name, n)
    cached = _target_cache.get(key)
    if cached is not None:
        return cached
    scored = score_stocks(
        universe,
        strategy.factors,
        as_of=as_of,
        db_path=research_db_path,
        groups=strategy.groups or None,
        min_groups=strategy.min_groups,
    )
    target = [str(code) for code in scored.head(n).index]
    _target_cache[key] = target
    return target


def build_advisory(
    target: list[str],
    held: dict[str, int],
    *,
    strategy_name: str,
    universe: set[str] | None = None,
) -> list[dict]:
    """Pure diff: target ranking vs current holdings → advisory items.

    BUY = in target, not held. HOLD = in target and held. SELL = held but no
    longer in the target top-N. ``universe`` scopes SELL to this sleeve's own
    stocks — without it the US stock advisory would tell you to sell your KR
    holdings and US ETFs just because they aren't in the US-stock top-N.
    No quantities/notional (advisory, not orders)."""
    n = len(target)
    weight = round(1.0 / n, 4) if n else 0.0
    rank = {t: i + 1 for i, t in enumerate(target)}
    items: list[dict] = []
    for t in target:
        items.append({
            "ticker": t,
            "action": "BUY" if held.get(t, 0) <= 0 else "HOLD",
            "rank": rank[t],
            "target_weight": weight,
            "held_qty": int(held.get(t, 0)),
            "reason": f"{strategy_name} 상위 {rank[t]}위",
        })
    for t, qty in held.items():
        in_sleeve = universe is None or t in universe
        if t not in rank and in_sleeve and int(qty) > 0:
            items.append({
                "ticker": t,
                "action": "SELL",
                "rank": None,
                "target_weight": 0.0,
                "held_qty": int(qty),
                "reason": "전략 목표(top-N) 이탈",
            })
    return items


async def _toss_holdings(toss_client) -> tuple[dict[str, int], bool]:
    """(held {ticker: qty}, toss_configured). Never raises — advisory works even
    when Toss is unconfigured (then it just shows the full target as BUYs)."""
    if toss_client is None:
        try:
            from backend.app.services.toss.rest_client import TossRestClient

            toss_client = TossRestClient()
        except Exception:  # noqa: BLE001 - Toss optional for advisory
            return {}, False
    if not getattr(toss_client, "is_configured", False):
        return {}, False
    try:
        balance = await toss_client.get_balance()
        held = {}
        for p in balance.positions:
            code = getattr(p, "stock_code", None) or getattr(p, "symbol", "")
            qty = int(getattr(p, "quantity", 0) or 0)
            if code and qty > 0:
                held[code] = qty
        return held, True
    except Exception:  # noqa: BLE001 - live broker best-effort
        return {}, False


async def generate_us_advisory(
    strategy_name: str = DEFAULT_US_STRATEGY,
    *,
    top_n: int | None = None,
    toss_client=None,
) -> dict:
    """Rank US_LARGE by the US strategy as-of the latest US price date, diff vs
    Toss holdings, return advisory suggestions (no execution)."""
    strategy = load_strategy(strategy_name)
    db_path = str(research_db_path)
    as_of = _latest_us_price_date(db_path)
    if as_of is None:
        return {"strategy": strategy_name, "error": "no US price data", "advisory": []}

    universe = get_universe(strategy.universe, as_of=as_of, db_path=research_db_path)
    n = top_n or strategy.top_n
    target = _ranked_target(strategy, strategy_name, universe, as_of, n)

    held, toss_configured = await _toss_holdings(toss_client)
    return {
        "as_of": as_of.isoformat(),
        "strategy": strategy_name,
        "universe": strategy.universe,
        "target_n": n,
        "toss_configured": toss_configured,
        # scope SELL to this sleeve's universe (KR holdings / US ETFs excluded)
        "advisory": build_advisory(
            target, held, strategy_name=strategy_name, universe=set(universe)
        ),
    }
