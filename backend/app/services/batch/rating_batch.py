"""매수/매도축 등급 배치 러너 (Phase T4, 2-슬리브 T10): EOD 전체 재계산 + 인트라데이 손절 감시.

Lane A(EOD, 장 마감 후): 이제 단일 패스가 아니라 **KR 주식 슬리브 + KR ETF
슬리브**로 나뉜 2-패스로 ``stock_ratings``를 갱신한다 — ETF는 유니버스가
겹치지 않는 완전히 다른 전략(로테이션)으로 채점해야 하며, 주식 전략의
extras(보유·관심·기존 평가 종목)에 ETF 코드가 섞여 들어가면 그 전략의
스코어러가 ETF를 잘못 채점해 기존 ETF 등급을 덮어써 버린다(클로버링 버그) —
그래서 ETF 유니버스 집합을 먼저 구해 주식 슬리브의 extras에서 차감한다.
ETF 슬리브는 quintile이 아니라 순위 기반(로테이션 시맨틱, 1위 STRONG_BUY 등)
으로 등급을 재매핑한다(``remap_etf_grades``). 이후 현재 보유 포지션에 대해
매도축 규칙(``sell_axis.rate_position``)을 적용해 ``position_ratings``를
갱신한다 — 포지션이 어느 슬리브에 속하는지에 따라 percentile/약점 그룹/NAV
비중(``sleeve_etf_weight``)을 다르게 적용한다.

Lane B(INTRADAY, 장중): 팩터/유니버스 재계산 없이 브로커 잔고의
``pl_rate``만 다시 읽어 손절 라인(``settings.RATING_STOP_LOSS_PCT``) 도달
여부만 확인한다 — 실시간 가격 주입이 없으므로 그 외 등급은 직전 EOD 값을
그대로 유지한다.

두 레인 모두 조회에 실패한 브로커/계좌는 건너뛰고, 성공한 계좌만
``store.delete_position_ratings_for_accounts``로 스코프를 좁혀 재삽입한다
(실패한 계좌의 직전 평가를 보존하기 위함).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.services.batch.daily_analysis import latest_research_price_date
from backend.app.services.brokers.base import BrokerAccountRef
from backend.app.services.kis.rest_client import KISRestClient
from backend.app.services.ratings import store
from backend.app.services.ratings.buy_axis import (
    BuyRating,
    BuyRatingsResult,
    compute_buy_ratings,
    resolve_rating_strategy,
)
from backend.app.services.ratings.sell_axis import PositionContext, rate_position
from backend.app.services.toss.rest_client import TossRestClient
from research.backtest.engine import get_universe
from research.factors.common import normalize_code
from shared.db.models import Setting, WatchlistEntry
from shared.db.session import service_session
from shared.domain.account import AccountType, BrokerType
from shared.domain.strategy import StrategyDefinition

logger = logging.getLogger(__name__)

PRUNE_AFTER_DAYS = 30


class _FetchedAccount:
    __slots__ = ("broker", "account_key", "positions", "nav", "holding_count")

    def __init__(
        self,
        broker: str,
        account_key: str,
        positions: list[Any],
        nav: float,
    ) -> None:
        self.broker = broker
        self.account_key = account_key
        self.positions = positions
        self.nav = nav
        self.holding_count = len(positions)


async def run_rating_eod(strategy_name: str | None = None) -> dict:
    """매수축 전체 재계산(주식 슬리브 + ETF 슬리브) + 매도축 보유 포지션 재평가 (Lane A)."""

    started_at = datetime.now()
    resolved_name = strategy_name or await _read_rating_strategy_setting()
    strategy, strategy_warning = resolve_rating_strategy(resolved_name)

    etf_setting_value = await _read_etf_strategy_setting()
    etf_strategy, etf_strategy_warning = resolve_etf_strategy(etf_setting_value)

    sleeve_etf_weight = await _read_sleeve_etf_weight_setting()

    accounts, succeeded_keys, error_count = await _fetch_broker_accounts()
    etf_set = await etf_universe_codes()

    held_codes = {
        normalize_code(pos.stock_code) for account in accounts for pos in account.positions
    }
    watchlist_codes = await _watchlist_codes()
    # ETF 코드는 주식 슬리브 extras에서 반드시 차감한다 — 그렇지 않으면 주식
    # 전략의 스코어러가 ETF를 채점(대개 NO_DATA)해 기존 ETF 등급을 덮어쓴다.
    stock_extras = (
        held_codes | watchlist_codes | set(await store.existing_rating_codes())
    ) - etf_set

    warnings: list[str] = []
    if strategy_warning:
        warnings.append(strategy_warning)
    if etf_strategy_warning:
        warnings.append(etf_strategy_warning)

    async with store.RATING_LOCK:
        stock_result = await asyncio.to_thread(
            compute_buy_ratings, strategy, stock_extras, as_of=None
        )
        stock_stored = await store.upsert_stock_ratings(
            stock_result.ratings, stock_result.strategy_name, stock_result.as_of
        )
        warnings.extend(stock_result.warnings)

        etf_result: BuyRatingsResult | None = None
        etf_stored = 0
        if etf_strategy is not None:
            etf_raw_result = await asyncio.to_thread(
                compute_buy_ratings, etf_strategy, (), as_of=None
            )
            etf_result = remap_etf_grades(etf_raw_result, top_n=etf_strategy.top_n)
            etf_stored = await store.upsert_stock_ratings(
                etf_result.ratings, etf_result.strategy_name, etf_result.as_of
            )
            warnings.extend(etf_result.warnings)

    stock_universe_codes = {
        rating.code for rating in stock_result.ratings[: stock_result.universe_size]
    }
    stock_percentile_by_code: dict[str, float | None] = {}
    stock_weakest_group_by_code: dict[str, str | None] = {}
    for rating in stock_result.ratings:
        stock_percentile_by_code[rating.code] = rating.percentile
        stock_weakest_group_by_code[rating.code] = rating.weakest_group

    etf_universe_codes_scored: set[str] = set()
    etf_percentile_by_code: dict[str, float | None] = {}
    etf_weakest_group_by_code: dict[str, str | None] = {}
    if etf_result is not None:
        etf_universe_codes_scored = {
            rating.code for rating in etf_result.ratings[: etf_result.universe_size]
        }
        for rating in etf_result.ratings:
            etf_percentile_by_code[rating.code] = rating.percentile
            etf_weakest_group_by_code[rating.code] = rating.weakest_group

    position_rows = []
    for account in accounts:
        for pos in account.positions:
            code = normalize_code(pos.stock_code)
            pl_rate = _to_float(pos.unrealized_pl_rate)
            position_value = _to_float(pos.evaluation_amount)
            is_us = not code.isdigit() or (
                (pos.market_country or "").upper() not in ("", "KR")
            )
            account_nav = account.nav or 0.0
            if code in etf_set:
                percentile = etf_percentile_by_code.get(code)
                weakest_group = etf_weakest_group_by_code.get(code)
                in_universe = code in etf_universe_codes_scored
                sleeve_strategy = etf_strategy or strategy
                sleeve_nav = account_nav * sleeve_etf_weight
            else:
                percentile = stock_percentile_by_code.get(code)
                weakest_group = stock_weakest_group_by_code.get(code)
                in_universe = code in stock_universe_codes
                sleeve_strategy = strategy
                sleeve_nav = account_nav * (1 - sleeve_etf_weight)
            ctx = PositionContext(
                code=code,
                pl_rate=pl_rate,
                percentile=percentile,
                weakest_group=weakest_group,
                position_value=position_value,
                nav=sleeve_nav or None,
                holding_count=account.holding_count or None,
                in_universe=in_universe,
                is_us=is_us,
            )
            sell_grade, reason = rate_position(
                ctx, sleeve_strategy, stop_loss_pct=settings.RATING_STOP_LOSS_PCT
            )
            position_rows.append(
                store.PositionRatingRow(
                    broker=account.broker,
                    account_key=account.account_key,
                    code=code,
                    sell_grade=sell_grade,
                    reason=reason,
                    pl_rate=pl_rate,
                    entry_price=_to_float(pos.avg_buy_price),
                )
            )

    await store.delete_position_ratings_for_accounts(succeeded_keys)
    position_stored = await store.upsert_position_ratings(position_rows, lane="EOD")

    finished_at = datetime.now()
    total_stored = stock_stored + etf_stored
    total_universe_size = stock_result.universe_size + (
        etf_result.universe_size if etf_result is not None else 0
    )
    detail = {
        "stock": stock_result.strategy_name,
        "etf": etf_result.strategy_name if etf_result is not None else None,
        "accounts_ok": sorted(succeeded_keys),
        "warnings": warnings,
    }
    await store.record_batch_run(
        lane="EOD",
        started_at=started_at,
        finished_at=finished_at,
        universe_size=total_universe_size,
        stored_count=total_stored,
        error_count=error_count,
        detail=detail,
    )
    await store.prune(older_than_days=PRUNE_AFTER_DAYS)

    summary = {
        "lane": "EOD",
        "as_of": stock_result.as_of,
        "strategy": stock_result.strategy_name,
        "etf_strategy": etf_result.strategy_name if etf_result is not None else None,
        "universe_size": total_universe_size,
        "stock_ratings_stored": total_stored,
        "position_ratings_stored": position_stored,
        "accounts_ok": sorted(succeeded_keys),
        "error_count": error_count,
        "warnings": warnings,
    }
    logger.info("rating batch EOD %s", summary)
    return summary


async def run_rating_intraday() -> dict:
    """브로커 ``pl_rate``만 재확인해 손절 라인 도달분을 SELL_NOW로 갱신 (Lane B)."""

    started_at = datetime.now()
    accounts, succeeded_keys, error_count = await _fetch_broker_accounts()

    existing = await store.get_position_ratings()
    existing_by_key = {
        (row["broker"], row["account_key"], row["code"]): row for row in existing
    }

    stop_loss_pct = settings.RATING_STOP_LOSS_PCT
    position_rows = []
    for account in accounts:
        for pos in account.positions:
            code = normalize_code(pos.stock_code)
            pl_rate = _to_float(pos.unrealized_pl_rate)
            prior = existing_by_key.get((account.broker, account.account_key, code))
            entry_price = _to_float(pos.avg_buy_price) or (
                prior["entry_price"] if prior else None
            )
            if pl_rate is not None and pl_rate <= stop_loss_pct:
                sell_grade = "SELL_NOW"
                reason = {
                    "rule": "STOP_LOSS",
                    "pl_rate": pl_rate,
                    "threshold": stop_loss_pct,
                }
            elif prior is not None:
                sell_grade = prior["sell_grade"]
                reason = prior["reason"]
            else:
                # 직전 EOD 평가가 없는 신규 포지션(장중 매수 등) — 손절 미도달이면
                # 다음 EOD가 정식 등급을 매길 때까지 NO_DATA로 표시한다.
                sell_grade = "HOLD"
                reason = {"rule": "NO_DATA"}
            position_rows.append(
                store.PositionRatingRow(
                    broker=account.broker,
                    account_key=account.account_key,
                    code=code,
                    sell_grade=sell_grade,
                    reason=reason,
                    pl_rate=pl_rate,
                    entry_price=entry_price,
                )
            )

    await store.delete_position_ratings_for_accounts(succeeded_keys)
    position_stored = await store.upsert_position_ratings(position_rows, lane="INTRADAY")

    finished_at = datetime.now()
    await store.record_batch_run(
        lane="INTRADAY",
        started_at=started_at,
        finished_at=finished_at,
        universe_size=None,
        stored_count=position_stored,
        error_count=error_count,
        detail={"accounts_ok": sorted(succeeded_keys)},
    )

    summary = {
        "lane": "INTRADAY",
        "position_ratings_stored": position_stored,
        "accounts_ok": sorted(succeeded_keys),
        "error_count": error_count,
    }
    logger.info("rating batch INTRADAY %s", summary)
    return summary


async def _read_rating_strategy_setting() -> str | None:
    async with service_session() as session:
        row = await session.get(Setting, "rating_strategy_name")
    return row.value if row is not None else None


async def _read_etf_strategy_setting() -> str | None:
    async with service_session() as session:
        row = await session.get(Setting, "etf_strategy_name")
    return row.value if row is not None else None


async def _read_sleeve_etf_weight_setting() -> float:
    async with service_session() as session:
        row = await session.get(Setting, "sleeve_etf_weight")
    try:
        value = float(row.value) if row is not None else settings.DEFAULT_SLEEVE_ETF_WEIGHT
    except (TypeError, ValueError):
        value = settings.DEFAULT_SLEEVE_ETF_WEIGHT
    return max(0.0, min(1.0, value))


def resolve_etf_strategy(
    setting_value: str | None,
) -> tuple[StrategyDefinition | None, str | None]:
    """ETF 슬리브 전략을 로드한다 (EOD 배치·``/compute`` 공용).

    ``resolve_rating_strategy``는 파일을 못 찾으면 항상 STOCK 기본 전략
    (``settings.DEFAULT_STRATEGY_NAME``)으로 폴백한다 — ETF 슬리브에는 유니버스가
    전혀 다른 부적합한 전략이므로, 그 폴백이 발생했다는 신호(경고 문자열이 채워짐)
    또는 ``FileNotFoundError``를 감지하면 대신 ETF 패스 자체를 건너뛴다
    (경고만 남기고 배치는 계속 진행 — 죽이지 않는다).
    """

    requested = setting_value or settings.DEFAULT_ETF_STRATEGY_NAME
    try:
        strategy, warning = resolve_rating_strategy(requested)
    except FileNotFoundError:
        return None, f"ETF strategy '{requested}' not found; skipping ETF sleeve pass."
    if warning:
        return None, f"ETF strategy '{requested}' not found; skipping ETF sleeve pass."
    return strategy, None


def remap_etf_grades(result: BuyRatingsResult, *, top_n: int) -> BuyRatingsResult:
    """ETF 로테이션 슬리브 전용: quintile 대신 순위 기반으로 매수 등급을 재부여한다.

    OK 등급만 score 내림차순으로 순위를 매겨 1위→STRONG_BUY, 2~``top_n``위→BUY,
    다음 2개→NEUTRAL, 나머지→AVOID로 재배정한다. percentile도 순위 기반
    ``(n - rank + 1) / n``으로 덮어써(1위→1.0, 꼴찌→1/n) 매도축 백분위 티어와의
    단조성을 유지한다. NO_DATA/UNSUPPORTED 행은 그대로 둔다(``/compute`` 공용).
    """

    ranked = sorted(
        (rating for rating in result.ratings if rating.status == "OK"),
        key=lambda rating: rating.score if rating.score is not None else float("-inf"),
        reverse=True,
    )
    n = len(ranked)
    remapped_by_code: dict[str, BuyRating] = {}
    for idx, rating in enumerate(ranked):
        rank = idx + 1
        if rank == 1:
            grade = "STRONG_BUY"
        elif rank <= top_n:
            grade = "BUY"
        elif rank <= top_n + 2:
            grade = "NEUTRAL"
        else:
            grade = "AVOID"
        remapped_by_code[rating.code] = BuyRating(
            code=rating.code,
            status=rating.status,
            buy_grade=grade,
            score=rating.score,
            percentile=(n - rank + 1) / n,
            weakest_group=rating.weakest_group,
        )

    ratings = [remapped_by_code.get(rating.code, rating) for rating in result.ratings]
    return BuyRatingsResult(
        as_of=result.as_of,
        strategy_name=result.strategy_name,
        universe_size=result.universe_size,
        ratings=ratings,
        warnings=result.warnings,
    )


async def etf_universe_codes() -> set[str]:
    """ETF_KR 유니버스 코드 집합(정규화됨) — 최신 리서치 가격일 기준.

    EOD 배치(주식 슬리브 extras 차감 + 포지션 슬리브 라우팅)와 ``/compute``
    (코드가 ETF인지 판별)가 공유한다.
    """

    as_of_date = await asyncio.to_thread(latest_research_price_date)
    codes = await asyncio.to_thread(get_universe, "ETF_KR", as_of=as_of_date)
    return {normalize_code(code) for code in codes}


async def _watchlist_codes() -> set[str]:
    async with service_session() as session:
        result = await session.execute(select(WatchlistEntry.stock_code))
        return {normalize_code(row[0]) for row in result.all()}


async def _fetch_broker_accounts() -> tuple[list[_FetchedAccount], set[str], int]:
    """모든 KIS 계좌 + Toss 잔고를 조회한다. 계좌별 실패는 건너뛴다.

    (매도축 온디맨드 재계산에서도 재사용될 수 있도록 브로커별 시도/실패를
    독립시켜, 한 계좌 실패가 나머지 계좌 처리를 막지 않게 한다.)
    """

    accounts: list[_FetchedAccount] = []
    succeeded_keys: set[str] = set()
    error_count = 0

    kis_client = KISRestClient()
    for account_type in AccountType:
        try:
            portfolio = await kis_client.get_balance(account_type)
        except Exception:
            logger.exception(
                "rating batch: KIS balance fetch failed account=%s", account_type.value
            )
            error_count += 1
            continue
        account_key = account_type.value
        accounts.append(
            _FetchedAccount(
                broker=BrokerType.KIS.value,
                account_key=account_key,
                positions=list(portfolio.positions),
                nav=_to_float(portfolio.summary.total_evaluation_amount) or 0.0,
            )
        )
        succeeded_keys.add(account_key)

    async with service_session() as session:
        rows = await _settings_map(session)
    toss_client = TossRestClient.from_settings_map(rows)
    if toss_client.is_configured:
        try:
            account_id = rows.get("toss_account_seq") or (
                str(settings.TOSS_ACCOUNT_SEQ)
                if settings.TOSS_ACCOUNT_SEQ is not None
                else None
            )
            portfolio = await toss_client.get_balance(
                BrokerAccountRef(broker=BrokerType.TOSS, account_id=account_id)
            )
            account_key = f"TOSS:{portfolio.account_id}"
            accounts.append(
                _FetchedAccount(
                    broker=BrokerType.TOSS.value,
                    account_key=account_key,
                    positions=list(portfolio.positions),
                    nav=_to_float(portfolio.summary.total_evaluation_amount) or 0.0,
                )
            )
            succeeded_keys.add(account_key)
        except Exception:
            logger.exception("rating batch: Toss balance fetch failed")
            error_count += 1

    return accounts, succeeded_keys, error_count


async def _settings_map(session) -> dict[str, str]:
    result = await session.execute(select(Setting))
    return {row.key: row.value for row in result.scalars()}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
