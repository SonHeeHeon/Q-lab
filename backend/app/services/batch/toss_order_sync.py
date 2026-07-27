"""Scheduled synchronization of Toss order fills into the trades table."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.services.toss.rest_client import (
    ORDER_STATUS_FILLED,
    TossOrderExecution,
    TossRestClient,
    TossRestError,
)
from shared.db.models import Trade
from shared.db.session import service_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TossOrderSyncResult:
    account_seq: int | None
    start_date: date
    end_date: date
    seen: int
    imported: int
    updated: int
    skipped: int
    trade_ids: list[int]
    notes: list[str]


async def sync_toss_orders_once(
    *,
    session_factory=None,
    client: TossRestClient | None = None,
    lookback_days: int | None = None,
) -> TossOrderSyncResult:
    """Fetch recent Toss order fills and upsert them into the local trades table.

    Orders placed by this app are matched to an existing local `trades` row via
    `Trade.kis_order_no == orderId` and updated in place. Orders placed
    directly in the Toss app (no local row) are inserted as new Trade rows
    with broker="TOSS", account_type=None. Idempotent: re-running never
    double-inserts, matched purely by orderId.
    """

    resolved_client = client or TossRestClient()
    query_end = date.today()
    days = (
        lookback_days
        if lookback_days is not None
        else settings.TOSS_ORDER_SYNC_LOOKBACK_DAYS
    )
    query_start = query_end - timedelta(days=max(1, days))
    notes: list[str] = []

    if not resolved_client.is_configured:
        return TossOrderSyncResult(
            account_seq=None,
            start_date=query_start,
            end_date=query_end,
            seen=0,
            imported=0,
            updated=0,
            skipped=0,
            trade_ids=[],
            notes=["Toss client is not configured; skipped"],
        )

    account_seq = await resolved_client.resolve_account_seq()

    executions: list[TossOrderExecution] = []
    try:
        executions.extend(
            await resolved_client.list_orders(status="OPEN", account_seq=account_seq)
        )
    except TossRestError as exc:
        logger.warning("toss order sync: OPEN order listing failed: %s", exc)
        notes.append(f"OPEN order listing failed: {exc}")

    try:
        executions.extend(
            await resolved_client.list_orders(
                status="CLOSED",
                since=query_start,
                until=query_end,
                account_seq=account_seq,
            )
        )
    except TossRestError as exc:
        # Toss's CLOSED order-history listing is not yet supported by the live
        # API (`400 closed-not-supported` per docs/toss_openapi.json's
        # PaginatedOrderResponse description as of this writing). Tolerate
        # this so OPEN-derived fills (e.g. PARTIAL_FILLED) still sync.
        logger.info("toss order sync: CLOSED order listing unavailable: %s", exc)
        notes.append(f"CLOSED order listing unavailable: {exc}")

    fills_by_order_id: dict[str, TossOrderExecution] = {}
    for execution in executions:
        if not execution.order_id or not execution.is_filled:
            continue
        fills_by_order_id[execution.order_id] = execution

    imported = 0
    updated = 0
    skipped = 0
    trade_ids: list[int] = []

    factory = session_factory or service_session
    async with factory() as session:
        for execution in fills_by_order_id.values():
            existing = await _find_trade_by_order_id(session, execution.order_id)
            if existing is not None:
                _apply_toss_execution(existing, execution)
                updated += 1
                trade_ids.append(existing.id)
                continue

            if not execution.symbol:
                skipped += 1
                notes.append(f"skipped {execution.order_id}: missing symbol")
                continue
            if execution.side not in {"BUY", "SELL"}:
                skipped += 1
                notes.append(f"skipped {execution.order_id}: missing buy/sell side")
                continue

            trade = _trade_from_toss_execution(execution)
            session.add(trade)
            await session.flush()
            trade_ids.append(trade.id)
            imported += 1

        await session.commit()

    logger.info(
        "toss order sync account_seq=%s seen=%s imported=%s updated=%s skipped=%s notes=%s",
        account_seq,
        len(fills_by_order_id),
        imported,
        updated,
        skipped,
        notes,
    )

    return TossOrderSyncResult(
        account_seq=account_seq,
        start_date=query_start,
        end_date=query_end,
        seen=len(fills_by_order_id),
        imported=imported,
        updated=updated,
        skipped=skipped,
        trade_ids=trade_ids,
        notes=notes,
    )


async def run_toss_order_sync(
    *,
    lookback_days: int | None = None,
) -> TossOrderSyncResult | None:
    """Scheduler entrypoint: sync Toss order fills for the configured account."""

    client = TossRestClient()
    if not client.is_configured:
        logger.info("toss order sync skipped: Toss credentials not configured")
        return None
    try:
        return await sync_toss_orders_once(client=client, lookback_days=lookback_days)
    except TossRestError as exc:
        logger.warning("toss order sync failed: %s", exc)
        return None
    except Exception:
        logger.exception("toss order sync unexpected failure")
        return None


async def _find_trade_by_order_id(session: AsyncSession, order_id: str) -> Trade | None:
    result = await session.execute(
        select(Trade)
        .where(Trade.broker == "TOSS", Trade.kis_order_no == order_id)
        .order_by(Trade.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _apply_toss_execution(trade: Trade, execution: TossOrderExecution) -> None:
    now = datetime.now()
    trade.last_checked_at = now
    trade.raw_execution = json.dumps(execution.raw, ensure_ascii=False, default=str)

    if trade.submitted_at is None:
        trade.submitted_at = execution.ordered_at or trade.executed_at

    trade.status = execution.status
    trade.filled_quantity = max(trade.filled_quantity or 0, int(execution.filled_quantity))
    if execution.avg_filled_price is not None:
        trade.filled_price = execution.avg_filled_price
        trade.price = execution.avg_filled_price
    trade.fees = _max_decimal(trade.fees, execution.commission)
    trade.taxes = _max_decimal(trade.taxes, execution.tax)

    if execution.filled_at is not None:
        trade.filled_at = execution.filled_at
        trade.executed_at = execution.filled_at
    elif execution.status == ORDER_STATUS_FILLED and trade.filled_at is None:
        trade.filled_at = now
        trade.executed_at = now

    if execution.canceled_at is not None:
        trade.canceled_at = execution.canceled_at


def _trade_from_toss_execution(execution: TossOrderExecution) -> Trade:
    now = datetime.now()
    quantity = execution.order_quantity or execution.filled_quantity
    price = execution.avg_filled_price or execution.order_price or Decimal("0")
    filled_at = execution.filled_at
    submitted_at = execution.ordered_at or filled_at or now
    raw_execution = json.dumps(execution.raw, ensure_ascii=False, default=str)
    return Trade(
        broker="TOSS",
        account_type=None,
        stock_code=execution.symbol or "",
        direction=execution.side,
        quantity=int(quantity),
        price=price,
        executed_at=filled_at or submitted_at,
        kis_order_no=execution.order_id,
        status=execution.status,
        submitted_at=submitted_at,
        filled_quantity=int(execution.filled_quantity),
        filled_price=execution.avg_filled_price,
        fees=execution.commission or Decimal("0"),
        taxes=execution.tax or Decimal("0"),
        filled_at=filled_at,
        canceled_at=execution.canceled_at,
        last_checked_at=now,
        raw_order=json.dumps(
            {"source": "toss_order_sync", "order_id": execution.order_id},
            ensure_ascii=False,
        ),
        raw_execution=raw_execution,
    )


def _max_decimal(current: Decimal | None, candidate: Decimal | None) -> Decimal:
    current_value = current if current is not None else Decimal("0")
    candidate_value = candidate if candidate is not None else Decimal("0")
    return max(current_value, candidate_value)
