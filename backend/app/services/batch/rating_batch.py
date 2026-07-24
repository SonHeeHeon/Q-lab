"""매수/매도축 등급 배치 러너 (Phase T4): EOD 전체 재계산 + 인트라데이 손절 감시.

Lane A(EOD, 장 마감 후): 전략 유니버스 전체를 재채점해 ``stock_ratings``를
갱신하고, 현재 보유 포지션에 대해 매도축 규칙(``sell_axis.rate_position``)을
적용해 ``position_ratings``를 갱신한다.

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
from backend.app.services.brokers.base import BrokerAccountRef
from backend.app.services.kis.rest_client import KISRestClient
from backend.app.services.ratings import store
from backend.app.services.ratings.buy_axis import (
    compute_buy_ratings,
    resolve_rating_strategy,
)
from backend.app.services.ratings.sell_axis import PositionContext, rate_position
from backend.app.services.toss.rest_client import TossRestClient
from research.factors.common import normalize_code
from shared.db.models import Setting, WatchlistEntry
from shared.db.session import service_session
from shared.domain.account import AccountType, BrokerType

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
    """매수축 전체 재계산 + 매도축 보유 포지션 재평가 (Lane A)."""

    started_at = datetime.now()
    resolved_name = strategy_name or await _read_rating_strategy_setting()
    strategy, strategy_warning = resolve_rating_strategy(resolved_name)

    accounts, succeeded_keys, error_count = await _fetch_broker_accounts()

    held_codes = {
        normalize_code(pos.stock_code) for account in accounts for pos in account.positions
    }
    watchlist_codes = await _watchlist_codes()
    extras = held_codes | watchlist_codes | set(await store.existing_rating_codes())

    async with store.RATING_LOCK:
        result = await asyncio.to_thread(
            compute_buy_ratings, strategy, extras, as_of=None
        )
        stock_stored = await store.upsert_stock_ratings(
            result.ratings, result.strategy_name, result.as_of
        )

    universe_codes = {
        rating.code for rating in result.ratings[: result.universe_size]
    }
    percentile_by_code: dict[str, float | None] = {}
    weakest_group_by_code: dict[str, str | None] = {}
    for rating in result.ratings:
        percentile_by_code[rating.code] = rating.percentile
        weakest_group_by_code[rating.code] = rating.weakest_group

    position_rows = []
    for account in accounts:
        for pos in account.positions:
            code = normalize_code(pos.stock_code)
            pl_rate = _to_float(pos.unrealized_pl_rate)
            position_value = _to_float(pos.evaluation_amount)
            is_us = not code.isdigit() or (
                (pos.market_country or "").upper() not in ("", "KR")
            )
            ctx = PositionContext(
                code=code,
                pl_rate=pl_rate,
                percentile=percentile_by_code.get(code),
                weakest_group=weakest_group_by_code.get(code),
                position_value=position_value,
                nav=account.nav or None,
                holding_count=account.holding_count or None,
                in_universe=code in universe_codes,
                is_us=is_us,
            )
            sell_grade, reason = rate_position(
                ctx, strategy, stop_loss_pct=settings.RATING_STOP_LOSS_PCT
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
    warnings = list(result.warnings)
    if strategy_warning:
        warnings.append(strategy_warning)
    detail = {
        "strategy": result.strategy_name,
        "accounts_ok": sorted(succeeded_keys),
        "warnings": warnings,
    }
    await store.record_batch_run(
        lane="EOD",
        started_at=started_at,
        finished_at=finished_at,
        universe_size=result.universe_size,
        stored_count=stock_stored,
        error_count=error_count,
        detail=detail,
    )
    await store.prune(older_than_days=PRUNE_AFTER_DAYS)

    summary = {
        "lane": "EOD",
        "as_of": result.as_of,
        "strategy": result.strategy_name,
        "universe_size": result.universe_size,
        "stock_ratings_stored": stock_stored,
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
