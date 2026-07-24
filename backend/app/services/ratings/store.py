"""매수/매도축 등급 영속 계층 (Phase T4).

``stock_ratings``/``position_ratings``/``rating_batch_runs`` 테이블에 대한
유일한 쓰기·읽기 통로다. EOD/인트라데이 배치(``batch/rating_batch.py``)와
API 레이어(T5, on-demand 재계산 포함)가 모두 이 모듈을 거쳐야 한다 —
``RATING_LOCK``이 두 경로의 쓰기를 직렬화해 동시 upsert로 인한 경합을 막는다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from shared.db.models import PositionRating, RatingBatchRun, StockRating
from shared.db.session import service_session

# 배치(rating_batch.py)와 온디맨드 재계산(API, T5)이 공유하는 단일-writer 락.
# 두 경로 모두 upsert 전에 이 락을 잡아야 stock_ratings/position_ratings에
# 대한 동시 쓰기가 서로 덮어쓰지 않는다.
RATING_LOCK = asyncio.Lock()


class BuyRatingLike(Protocol):
    """``buy_axis.BuyRating``과 호환되는 최소 인터페이스."""

    code: str
    status: str
    buy_grade: str | None
    score: float | None
    percentile: float | None
    weakest_group: str | None


@dataclass(frozen=True, slots=True)
class PositionRatingRow:
    """``upsert_position_ratings``에 넘기는 매도축 평가 1행."""

    broker: str
    account_key: str
    code: str
    sell_grade: str
    reason: dict[str, Any]
    pl_rate: float | None
    entry_price: float | None


def _normalize_code(code: str) -> str:
    text = str(code).strip().upper()
    return text.zfill(6) if text.isdigit() else text


async def upsert_stock_ratings(
    rows: Sequence[BuyRatingLike],
    strategy_name: str,
    as_of: str,
) -> int:
    """매수축 평가 결과를 ``stock_ratings``에 종목당 1행으로 upsert한다."""

    if not rows:
        return 0
    as_of_date = Date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    now = datetime.now()
    payload = [
        {
            "code": _normalize_code(row.code),
            "status": row.status,
            "buy_grade": row.buy_grade,
            "score": row.score,
            "percentile": row.percentile,
            "weakest_group": row.weakest_group,
            "strategy_name": strategy_name,
            "as_of": as_of_date,
            "updated_at": now,
        }
        for row in rows
    ]
    async with service_session() as session:
        stmt = insert(StockRating).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[StockRating.code],
            set_={
                "status": stmt.excluded.status,
                "buy_grade": stmt.excluded.buy_grade,
                "score": stmt.excluded.score,
                "percentile": stmt.excluded.percentile,
                "weakest_group": stmt.excluded.weakest_group,
                "strategy_name": stmt.excluded.strategy_name,
                "as_of": stmt.excluded.as_of,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await session.execute(stmt)
        await session.commit()
    return len(payload)


async def upsert_position_ratings(rows: Sequence[PositionRatingRow], lane: str) -> int:
    """매도축 평가 결과를 ``position_ratings``에 계좌×종목당 1행으로 upsert한다."""

    if not rows:
        return 0
    now = datetime.now()
    payload = [
        {
            "broker": row.broker,
            "account_key": row.account_key,
            "code": _normalize_code(row.code),
            "sell_grade": row.sell_grade,
            "reason_json": json.dumps(row.reason, ensure_ascii=False),
            "pl_rate": row.pl_rate,
            "entry_price": row.entry_price,
            "lane": lane,
            "updated_at": now,
        }
        for row in rows
    ]
    async with service_session() as session:
        stmt = insert(PositionRating).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                PositionRating.broker,
                PositionRating.account_key,
                PositionRating.code,
            ],
            set_={
                "sell_grade": stmt.excluded.sell_grade,
                "reason_json": stmt.excluded.reason_json,
                "pl_rate": stmt.excluded.pl_rate,
                "entry_price": stmt.excluded.entry_price,
                "lane": stmt.excluded.lane,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await session.execute(stmt)
        await session.commit()
    return len(payload)


async def delete_position_ratings_for_accounts(account_keys: set[str]) -> int:
    """지정된 ``account_key`` 들의 기존 매도축 행을 재삽입 전에 지운다.

    잔고 조회에 실패한 계좌는 이 집합에서 빠져야 한다 — 그래야 실패한
    계좌의 기존(직전 성공분) 평가가 이번 배치에서 지워지지 않고 남는다.
    """

    if not account_keys:
        return 0
    async with service_session() as session:
        result = await session.execute(
            delete(PositionRating).where(PositionRating.account_key.in_(account_keys))
        )
        await session.commit()
    return int(result.rowcount or 0)


async def get_stock_ratings(codes: list[str]) -> list[dict[str, Any]]:
    """지정된 종목 코드들의 매수축 평가를 dict 목록으로 반환한다."""

    if not codes:
        return []
    normalized = [_normalize_code(code) for code in codes]
    async with service_session() as session:
        result = await session.execute(
            select(StockRating).where(StockRating.code.in_(normalized))
        )
        rows = result.scalars().all()
    return [_stock_rating_dict(row) for row in rows]


async def get_position_ratings() -> list[dict[str, Any]]:
    """모든 보유 포지션의 매도축 평가를 dict 목록으로 반환한다."""

    async with service_session() as session:
        result = await session.execute(select(PositionRating))
        rows = result.scalars().all()
    return [_position_rating_dict(row) for row in rows]


async def record_batch_run(
    lane: str,
    started_at: datetime,
    finished_at: datetime | None,
    universe_size: int | None,
    stored_count: int | None,
    error_count: int,
    detail: dict[str, Any] | None = None,
) -> None:
    """배치 갱신 이력을 ``rating_batch_runs``에 1행 기록한다(관측성용)."""

    async with service_session() as session:
        session.add(
            RatingBatchRun(
                lane=lane,
                started_at=started_at,
                finished_at=finished_at,
                universe_size=universe_size,
                stored_count=stored_count,
                error_count=error_count,
                detail_json=(
                    json.dumps(detail, ensure_ascii=False) if detail is not None else None
                ),
            )
        )
        await session.commit()


async def latest_runs() -> dict[str, dict[str, Any]]:
    """레인(EOD/INTRADAY)별 가장 최근 배치 실행을 dict로 반환한다(``/status`` 용)."""

    async with service_session() as session:
        result = await session.execute(
            select(RatingBatchRun).order_by(RatingBatchRun.started_at.desc())
        )
        rows = result.scalars().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.lane in latest:
            continue
        latest[row.lane] = _batch_run_dict(row)
    return latest


async def existing_rating_codes() -> list[str]:
    """이미 ``stock_ratings``에 있는 종목 코드 목록(EOD가 온디맨드 종목도 최신 유지)."""

    async with service_session() as session:
        result = await session.execute(select(StockRating.code))
        return [row[0] for row in result.all()]


async def prune(older_than_days: int = 30) -> None:
    """``updated_at``/``started_at`` 기준으로 오래된 행을 정리한다."""

    cutoff = datetime.now() - timedelta(days=older_than_days)
    async with service_session() as session:
        await session.execute(delete(StockRating).where(StockRating.updated_at < cutoff))
        await session.execute(
            delete(RatingBatchRun).where(RatingBatchRun.started_at < cutoff)
        )
        await session.commit()


def _stock_rating_dict(row: StockRating) -> dict[str, Any]:
    return {
        "code": row.code,
        "status": row.status,
        "buy_grade": row.buy_grade,
        "score": row.score,
        "percentile": row.percentile,
        "weakest_group": row.weakest_group,
        "strategy_name": row.strategy_name,
        "as_of": row.as_of.isoformat() if row.as_of else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _position_rating_dict(row: PositionRating) -> dict[str, Any]:
    try:
        reason = json.loads(row.reason_json)
    except (TypeError, ValueError):
        reason = {}
    return {
        "broker": row.broker,
        "account_key": row.account_key,
        "code": row.code,
        "sell_grade": row.sell_grade,
        "reason": reason,
        "pl_rate": row.pl_rate,
        "entry_price": row.entry_price,
        "lane": row.lane,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _batch_run_dict(row: RatingBatchRun) -> dict[str, Any]:
    try:
        detail = json.loads(row.detail_json) if row.detail_json else None
    except (TypeError, ValueError):
        detail = None
    return {
        "id": row.id,
        "lane": row.lane,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "universe_size": row.universe_size,
        "stored_count": row.stored_count,
        "error_count": row.error_count,
        "detail": detail,
    }
