"""Background reconciliation for KIS order execution status."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_, select

from backend.app.core.config import settings
from backend.app.services.kis.rest_client import (
    KISOrderExecution,
    KISRestClient,
    KISRestError,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NOT_FOUND,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_PENDING,
)
from shared.db.models import Account, Trade
from shared.db.session import service_session
from shared.domain.account import AccountType
from shared.domain.trade import TradeDirection

logger = logging.getLogger(__name__)

TRACKABLE_STATUSES = {
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PARTIALLY_FILLED,
}
TERMINAL_STATUSES = {ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED}


@dataclass(frozen=True, slots=True)
class OrderTrackResult:
    trade_id: int
    kis_order_no: str | None
    previous_status: str
    current_status: str
    changed: bool
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalOrderSyncResult:
    account_type: AccountType
    start_date: date
    end_date: date
    seen: int
    imported: int
    updated: int
    skipped: int
    trade_ids: list[int]
    notes: list[str]


class OrderTrackerService:
    """Long-running task that polls KIS for locally submitted open orders."""

    def __init__(
        self,
        *,
        kis_client: KISRestClient | None = None,
        poll_interval_seconds: int | None = None,
    ) -> None:
        self._kis_client = kis_client or KISRestClient()
        self._poll_interval_seconds = (
            poll_interval_seconds or settings.ORDER_TRACKER_POLL_INTERVAL_SECONDS
        )
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="kis-order-tracker")

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            self._stop_event = None

    async def _run(self) -> None:
        logger.info(
            "started KIS order tracker poll_interval=%ss",
            self._poll_interval_seconds,
        )
        while True:
            try:
                await track_pending_orders_once(kis_client=self._kis_client)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("KIS order tracker iteration failed")

            stop_event = self._stop_event
            if stop_event is None:
                return
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=max(1, self._poll_interval_seconds),
                )
                return
            except TimeoutError:
                continue


async def track_pending_orders_once(
    *,
    kis_client: KISRestClient | None = None,
    limit: int = 50,
) -> list[OrderTrackResult]:
    """Poll KIS once for stale local pending/partial orders."""

    now = datetime.now()
    cutoff = now - timedelta(seconds=settings.ORDER_TRACKER_POLL_INTERVAL_SECONDS)
    async with service_session() as session:
        stmt = (
            select(Trade.id)
            .where(
                Trade.status.in_(TRACKABLE_STATUSES),
                Trade.kis_order_no.is_not(None),
                or_(Trade.last_checked_at.is_(None), Trade.last_checked_at < cutoff),
            )
            .order_by(Trade.last_checked_at.is_not(None), Trade.last_checked_at, Trade.id)
            .limit(limit)
        )
        result = await session.execute(stmt)
        trade_ids = [int(row[0]) for row in result.all()]

    client = kis_client or KISRestClient()
    results: list[OrderTrackResult] = []
    for trade_id in trade_ids:
        results.append(await track_trade_once(trade_id, kis_client=client))
    return results


async def track_trade_until_terminal(
    trade_id: int,
    *,
    kis_client: KISRestClient | None = None,
    poll_interval_seconds: int = 5,
    timeout_seconds: int | None = None,
) -> OrderTrackResult:
    """Track one trade for a short bounded window after order submission."""

    client = kis_client or KISRestClient()
    deadline = datetime.now() + timedelta(
        seconds=timeout_seconds or settings.ORDER_TRACKER_ORDER_TIMEOUT_SECONDS
    )
    latest = await track_trade_once(trade_id, kis_client=client)
    while latest.current_status not in TERMINAL_STATUSES and datetime.now() < deadline:
        await asyncio.sleep(max(1, poll_interval_seconds))
        latest = await track_trade_once(trade_id, kis_client=client)
    return latest


async def track_trade_once(
    trade_id: int,
    *,
    kis_client: KISRestClient | None = None,
) -> OrderTrackResult:
    """Poll KIS for one local trade and apply execution data to service.db."""

    client = kis_client or KISRestClient()
    async with service_session() as session:
        trade = await session.get(Trade, trade_id)
        if trade is None:
            return OrderTrackResult(
                trade_id=trade_id,
                kis_order_no=None,
                previous_status="UNKNOWN",
                current_status="UNKNOWN",
                changed=False,
                note="local trade not found",
            )
        if not trade.kis_order_no:
            trade.last_checked_at = datetime.now()
            await session.commit()
            return OrderTrackResult(
                trade_id=trade.id,
                kis_order_no=None,
                previous_status=trade.status,
                current_status=trade.status,
                changed=False,
                note="missing KIS order number",
            )

        previous_status = trade.status
        account_type = AccountType(trade.account_type)
        start_date = _query_start_date(trade)
        end_date = date.today()

    try:
        execution = await client.get_order_execution(
            account_type,
            trade.kis_order_no,
            stock_code=trade.stock_code,
            start_date=start_date,
            end_date=end_date,
        )
    except KISRestError as exc:
        logger.warning("KIS order tracking failed trade_id=%s: %s", trade_id, exc)
        async with service_session() as session:
            trade = await session.get(Trade, trade_id)
            if trade is not None:
                trade.last_checked_at = datetime.now()
                trade.raw_execution = json.dumps(
                    {"error": str(exc), "payload": exc.payload},
                    ensure_ascii=False,
                    default=str,
                )
                await session.commit()
        return OrderTrackResult(
            trade_id=trade_id,
            kis_order_no=None,
            previous_status=previous_status,
            current_status=previous_status,
            changed=False,
            note=str(exc),
        )

    async with service_session() as session:
        trade = await session.get(Trade, trade_id)
        if trade is None:
            return OrderTrackResult(
                trade_id=trade_id,
                kis_order_no=execution.order_no,
                previous_status=previous_status,
                current_status=execution.status,
                changed=False,
                note="local trade disappeared before update",
            )
        _apply_execution(trade, execution)
        await session.commit()
        return OrderTrackResult(
            trade_id=trade.id,
            kis_order_no=trade.kis_order_no,
            previous_status=previous_status,
            current_status=trade.status,
            changed=previous_status != trade.status,
            note=None if execution.status != ORDER_STATUS_NOT_FOUND else "not found at KIS",
        )


async def sync_external_orders_once(
    account_type: AccountType,
    *,
    kis_client: KISRestClient | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    stock_code: str | None = None,
) -> ExternalOrderSyncResult:
    """Import broker-side orders that were not originally placed by this app."""

    client = kis_client or KISRestClient()
    query_end = end_date or date.today()
    query_start = start_date or query_end - timedelta(days=7)
    executions = await client.list_order_executions(
        account_type,
        start_date=query_start,
        end_date=query_end,
        stock_code=stock_code,
    )
    executions_by_order_no: dict[str, KISOrderExecution] = {}
    notes: list[str] = []
    for execution in executions:
        if not execution.order_no:
            notes.append("skipped KIS row without order number")
            continue
        executions_by_order_no[execution.order_no] = execution

    imported = 0
    updated = 0
    skipped = len(executions) - len(executions_by_order_no)
    trade_ids: list[int] = []

    async with service_session() as session:
        await _ensure_account_row(session, account_type)
        for execution in executions_by_order_no.values():
            existing = await _find_trade_by_order_no(
                session,
                account_type=account_type,
                order_no=execution.order_no,
            )
            if existing is not None:
                _apply_execution(existing, execution)
                updated += 1
                trade_ids.append(existing.id)
                continue

            if execution.stock_code is None:
                skipped += 1
                notes.append(f"skipped {execution.order_no}: missing stock code")
                continue
            if execution.direction is None:
                skipped += 1
                notes.append(f"skipped {execution.order_no}: missing buy/sell direction")
                continue

            trade = _trade_from_external_execution(execution)
            session.add(trade)
            await session.flush()
            trade_ids.append(trade.id)
            imported += 1

        await session.commit()

    return ExternalOrderSyncResult(
        account_type=account_type,
        start_date=query_start,
        end_date=query_end,
        seen=len(executions),
        imported=imported,
        updated=updated,
        skipped=skipped,
        trade_ids=trade_ids,
        notes=notes,
    )


def _apply_execution(trade: Trade, execution: KISOrderExecution) -> None:
    now = datetime.now()
    trade.last_checked_at = now
    trade.raw_execution = json.dumps(execution.raw, ensure_ascii=False, default=str)

    if trade.submitted_at is None:
        trade.submitted_at = trade.executed_at

    if execution.status == ORDER_STATUS_NOT_FOUND:
        return

    trade.status = execution.status
    trade.filled_quantity = max(trade.filled_quantity or 0, execution.filled_quantity)
    if execution.filled_price is not None:
        trade.filled_price = execution.filled_price
    trade.fees = _max_decimal(trade.fees, execution.fees)
    trade.taxes = _max_decimal(trade.taxes, execution.taxes)

    if execution.status in {ORDER_STATUS_FILLED, ORDER_STATUS_PARTIALLY_FILLED}:
        if execution.filled_price is not None:
            trade.price = execution.filled_price
        if execution.filled_at is not None:
            trade.filled_at = execution.filled_at
        elif execution.status == ORDER_STATUS_FILLED and trade.filled_at is None:
            trade.filled_at = now
        if trade.filled_at is not None:
            trade.executed_at = trade.filled_at

    if execution.status == ORDER_STATUS_CANCELED:
        trade.canceled_at = now


async def _find_trade_by_order_no(
    session,
    *,
    account_type: AccountType,
    order_no: str,
) -> Trade | None:
    result = await session.execute(
        select(Trade)
        .where(
            Trade.account_type == account_type.value,
            Trade.kis_order_no == order_no,
        )
        .order_by(Trade.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _ensure_account_row(session, account_type: AccountType) -> None:
    account = await session.get(Account, account_type.value)
    if account is not None:
        return

    configured_account = settings.kis_account(account_type)
    session.add(
        Account(
            type=account_type.value,
            app_key="[managed-by-env]",
            app_secret="[managed-by-env]",
            account_no=configured_account.account_no,
            is_active=configured_account.is_active,
        )
    )


def _trade_from_external_execution(execution: KISOrderExecution) -> Trade:
    now = datetime.now()
    status = (
        ORDER_STATUS_PENDING
        if execution.status == ORDER_STATUS_NOT_FOUND
        else execution.status
    )
    price = execution.filled_price or execution.order_price or Decimal("0")
    filled_at = execution.filled_at
    submitted_at = filled_at or now
    raw_execution = json.dumps(execution.raw, ensure_ascii=False, default=str)
    return Trade(
        account_type=execution.account_type.value,
        stock_code=execution.stock_code or "",
        direction=(execution.direction or TradeDirection.BUY).value,
        quantity=execution.order_quantity or execution.filled_quantity,
        price=price,
        executed_at=filled_at or submitted_at,
        kis_order_no=execution.order_no,
        status=status,
        submitted_at=submitted_at,
        filled_quantity=execution.filled_quantity,
        filled_price=execution.filled_price,
        fees=execution.fees,
        taxes=execution.taxes,
        filled_at=filled_at if status in {ORDER_STATUS_FILLED, ORDER_STATUS_PARTIALLY_FILLED} else None,
        canceled_at=now if status == ORDER_STATUS_CANCELED else None,
        last_checked_at=now,
        raw_order=json.dumps(
            {"source": "kis_external_sync", "order_no": execution.order_no},
            ensure_ascii=False,
        ),
        raw_execution=raw_execution,
    )


def _query_start_date(trade: Trade) -> date:
    reference = trade.submitted_at or trade.executed_at or datetime.now()
    return reference.date() - timedelta(days=3)


def _max_decimal(current: Decimal | None, candidate: Decimal | None) -> Decimal:
    current_value = current or Decimal("0")
    candidate_value = candidate or Decimal("0")
    return max(current_value, candidate_value)
