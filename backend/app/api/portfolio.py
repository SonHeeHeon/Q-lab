"""Portfolio REST API."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.schemas.portfolio import (
    ApiEnvelope,
    ApiError,
    OrderEnvelope,
    OrderEnvelopeData,
    OrderRequest,
    PortfolioEnvelope,
    PortfolioResponse,
    AccountSummaryResponse,
    BrokerOrderSyncAccountResult,
    BrokerOrderSyncEnvelope,
    BrokerOrderSyncRequest,
    BrokerOrderSyncResponse,
    TradePersistResult,
    UnifiedPortfolioEnvelope,
    UnifiedPortfolioResponse,
    UnifiedPositionResponse,
)
from backend.app.services.kis.rest_client import KISRestClient, KISRestError
from backend.app.core.config import settings
from backend.app.services.kis.order_tracker import (
    sync_external_orders_once,
    track_trade_until_terminal,
)
from backend.app.services.market_data.names import lookup_stock_names
from shared.db.models import Account, Trade
from shared.db.session import get_service_session
from shared.domain.account import AccountType

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])
logger = logging.getLogger(__name__)


def get_kis_rest_client() -> KISRestClient:
    return KISRestClient()


@router.get("", response_model=UnifiedPortfolioEnvelope)
async def get_unified_portfolio(
    kis_client: KISRestClient = Depends(get_kis_rest_client),
) -> UnifiedPortfolioEnvelope:
    results = await asyncio.gather(
        *(kis_client.get_balance(account_type) for account_type in AccountType),
        return_exceptions=True,
    )

    portfolios: list[PortfolioResponse] = []
    errors: list[dict[str, object]] = []
    for account_type, result in zip(AccountType, results, strict=True):
        if isinstance(result, Exception):
            errors.append(
                {
                    "account_type": account_type.value,
                    "message": str(result),
                }
            )
            continue
        portfolios.append(await _enrich_position_names(result))

    return UnifiedPortfolioEnvelope(
        data=_unified_response(portfolios, errors),
        error=None,
    )


@router.get("/{account_type}", response_model=PortfolioEnvelope)
async def get_portfolio_account(
    account_type: AccountType,
    kis_client: KISRestClient = Depends(get_kis_rest_client),
) -> PortfolioEnvelope | JSONResponse:
    try:
        portfolio = await kis_client.get_balance(account_type)
    except KISRestError as exc:
        return _error_response("KIS_BALANCE_FAILED", str(exc), exc)
    portfolio = await _enrich_position_names(portfolio)
    return PortfolioEnvelope(data=portfolio, error=None)


@router.post("/orders/sync", response_model=BrokerOrderSyncEnvelope)
async def sync_broker_orders(
    payload: BrokerOrderSyncRequest,
    kis_client: KISRestClient = Depends(get_kis_rest_client),
) -> BrokerOrderSyncEnvelope:
    """Import KIS app/HTS orders that do not yet exist in local trades."""

    started_at = datetime.now().astimezone()
    end_date = payload.end_date or date.today()
    start_date = payload.start_date or end_date - timedelta(days=7)
    account_types = [payload.account_type] if payload.account_type else list(AccountType)
    results: list[BrokerOrderSyncAccountResult] = []

    for account_type in account_types:
        try:
            result = await sync_external_orders_once(
                account_type,
                kis_client=kis_client,
                start_date=start_date,
                end_date=end_date,
                stock_code=payload.stock_code,
            )
            results.append(
                BrokerOrderSyncAccountResult(
                    account_type=result.account_type,
                    start_date=result.start_date,
                    end_date=result.end_date,
                    seen=result.seen,
                    imported=result.imported,
                    updated=result.updated,
                    skipped=result.skipped,
                    trade_ids=result.trade_ids,
                    notes=result.notes,
                    error=None,
                )
            )
        except KISRestError as exc:
            results.append(
                BrokerOrderSyncAccountResult(
                    account_type=account_type,
                    start_date=start_date,
                    end_date=end_date,
                    seen=0,
                    imported=0,
                    updated=0,
                    skipped=0,
                    trade_ids=[],
                    notes=[],
                    error=str(exc),
                )
            )

    return BrokerOrderSyncEnvelope(
        data=BrokerOrderSyncResponse(
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
            results=results,
        ),
        error=None,
    )


@router.post("/orders", response_model=OrderEnvelope, status_code=status.HTTP_201_CREATED)
async def place_order(
    request: OrderRequest,
    background_tasks: BackgroundTasks,
    kis_client: KISRestClient = Depends(get_kis_rest_client),
    session: AsyncSession = Depends(get_service_session),
) -> OrderEnvelope | JSONResponse:
    try:
        order = await kis_client.place_order(request)
    except KISRestError as exc:
        return _error_response("KIS_ORDER_FAILED", str(exc), exc)

    persistence = await _persist_trade_skeleton(session, order)
    if persistence.persisted and persistence.trade_id is not None and order.kis_order_no:
        background_tasks.add_task(_schedule_order_tracking, persistence.trade_id)
    return OrderEnvelope(
        data=OrderEnvelopeData(order=order, trade_persistence=persistence),
        error=None,
    )


async def _persist_trade_skeleton(
    session: AsyncSession,
    order,
) -> TradePersistResult:
    # This is intentionally a submission-side skeleton. The order tracker updates
    # it with broker fill state, actual price, fees, taxes, and fill timestamp.
    try:
        await _ensure_account_row(session, order.account_type)
        trade = Trade(
            account_type=order.account_type.value,
            stock_code=order.stock_code,
            direction=order.direction.value,
            quantity=order.quantity,
            price=order.price or Decimal("0"),
            executed_at=order.accepted_at,
            kis_order_no=order.kis_order_no,
            status="PENDING",
            submitted_at=order.accepted_at,
            filled_quantity=0,
            fees=Decimal("0"),
            taxes=Decimal("0"),
            raw_order=json.dumps(order.raw, ensure_ascii=False, default=str),
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)
    except Exception as exc:
        await session.rollback()
        return TradePersistResult(
            trade_id=None,
            persisted=False,
            note=f"Order accepted by KIS, but local trade insert failed: {exc}",
        )

    return TradePersistResult(
        trade_id=trade.id,
        persisted=True,
        note="Stored local order submission and queued KIS execution tracking.",
    )


async def _ensure_account_row(
    session: AsyncSession,
    account_type: AccountType,
) -> None:
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
    # Secret persistence/encryption belongs to the Settings API step. For now
    # this placeholder row only satisfies the trades.account_type FK.


def _error_response(code: str, message: str, exc: KISRestError) -> JSONResponse:
    envelope = ApiEnvelope(
        data=None,
        error=ApiError(
            code=code,
            message=message,
            details=exc.payload,
        ),
    )
    return JSONResponse(
        status_code=exc.status_code if exc.status_code and exc.status_code >= 400 else 502,
        content=envelope.model_dump(mode="json"),
    )


async def _enrich_position_names(portfolio: PortfolioResponse) -> PortfolioResponse:
    missing_codes = [
        position.stock_code
        for position in portfolio.positions
        if not position.name and position.stock_code
    ]
    if not missing_codes:
        return portfolio

    names = await asyncio.to_thread(lookup_stock_names, missing_codes)
    for position in portfolio.positions:
        if not position.name:
            position.name = names.get(position.stock_code) or position.stock_code
    return portfolio


def _unified_response(
    portfolios: list[PortfolioResponse],
    errors: list[dict[str, object]],
) -> UnifiedPortfolioResponse:
    accounts: list[AccountSummaryResponse] = []
    positions: list[UnifiedPositionResponse] = []

    total_value = Decimal("0")
    total_pl = Decimal("0")
    total_cost = Decimal("0")

    for portfolio in portfolios:
        summary = portfolio.summary
        account_value = summary.total_evaluation_amount or Decimal("0")
        account_cash = summary.cash_amount or Decimal("0")
        account_pl = summary.unrealized_pl or Decimal("0")
        account_cost = summary.purchase_amount or Decimal("0")
        account_pl_pct = _pct(account_pl, account_cost)

        total_value += account_value
        total_pl += account_pl
        total_cost += account_cost
        accounts.append(
            AccountSummaryResponse(
                account_type=portfolio.account_type,
                total_value=account_value,
                cash_balance=account_cash,
                total_pl=account_pl,
                total_pl_pct=account_pl_pct,
            )
        )

        for position in portfolio.positions:
            stock_name = position.name or position.stock_code
            positions.append(
                UnifiedPositionResponse(
                    account_type=portfolio.account_type,
                    stock_code=position.stock_code,
                    name=stock_name,
                    stock_name=stock_name,
                    quantity=position.quantity,
                    avg_buy_price=position.avg_buy_price,
                    current_price=position.current_price,
                    purchase_amount=position.purchase_amount,
                    evaluation_amount=position.evaluation_amount,
                    unrealized_pl=position.unrealized_pl,
                    unrealized_pl_rate=position.unrealized_pl_rate,
                )
            )

    return UnifiedPortfolioResponse(
        as_of=datetime.now().astimezone(),
        total_value=total_value,
        total_pl=total_pl,
        total_pl_pct=_pct(total_pl, total_cost),
        accounts=accounts,
        positions=positions,
        errors=errors,
    )


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return (numerator / denominator) * Decimal("100")


async def _schedule_order_tracking(trade_id: int) -> None:
    asyncio.create_task(
        _track_order_safely(trade_id),
        name=f"kis-order-track-{trade_id}",
    )


async def _track_order_safely(trade_id: int) -> None:
    try:
        await track_trade_until_terminal(trade_id)
    except Exception:
        logger.exception("KIS order tracking task failed trade_id=%s", trade_id)
