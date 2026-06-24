"""Portfolio REST API."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
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
from backend.app.services.toss.rest_client import TossRestClient, TossRestError
from backend.app.core.config import settings
from backend.app.services.brokers.base import BrokerAccountRef
from backend.app.services.kis.order_tracker import (
    sync_external_orders_once,
    track_trade_until_terminal,
)
from backend.app.services.market_data.fx import FxRate, FxRateError, get_fx_rate
from backend.app.services.market_data.names import lookup_stock_names
from backend.app.services.market_data.quotes import fetch_current_quotes
from shared.db.models import Account, Setting, Trade
from shared.db.session import get_service_session
from shared.domain.account import AccountType
from shared.domain.account import BrokerType

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])
logger = logging.getLogger(__name__)


def get_kis_rest_client() -> KISRestClient:
    return KISRestClient()


@router.get("", response_model=UnifiedPortfolioEnvelope)
async def get_unified_portfolio(
    kis_client: KISRestClient = Depends(get_kis_rest_client),
    broker: str = Query(default="ALL", pattern="^(ALL|KIS|TOSS)$"),
    session: AsyncSession = Depends(get_service_session),
) -> UnifiedPortfolioEnvelope:
    portfolios: list[PortfolioResponse] = []
    errors: list[dict[str, object]] = []
    selected_broker = str(broker).upper()

    if selected_broker in {"ALL", BrokerType.KIS.value}:
        results = await asyncio.gather(
            *(kis_client.get_balance(account_type) for account_type in AccountType),
            return_exceptions=True,
        )
        for account_type, result in zip(AccountType, results, strict=True):
            if isinstance(result, Exception):
                errors.append(
                    {
                        "broker": BrokerType.KIS.value,
                        "account_type": account_type.value,
                        "message": str(result),
                    }
                )
                continue
            result = await _enrich_position_prices(result, BrokerType.KIS)
            portfolios.append(await _enrich_position_names(result))

    if selected_broker in {"ALL", BrokerType.TOSS.value}:
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
                    BrokerAccountRef(
                        broker=BrokerType.TOSS,
                        account_id=account_id,
                    )
                )
                portfolio = await _enrich_position_prices(portfolio, BrokerType.TOSS)
                portfolios.append(await _enrich_position_names(portfolio))
            except Exception as exc:
                errors.append(
                    {
                        "broker": BrokerType.TOSS.value,
                        "message": str(exc),
                    }
                )
        elif selected_broker == BrokerType.TOSS.value:
            errors.append(
                {
                    "broker": BrokerType.TOSS.value,
                    "message": "Toss credentials are not configured.",
                }
            )

    fx_rate = await _portfolio_fx_rate(portfolios, errors)
    return UnifiedPortfolioEnvelope(
        data=_unified_response(portfolios, errors, fx_rate),
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
    portfolio = await _enrich_position_prices(portfolio, BrokerType.KIS)
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
        if request.broker is BrokerType.KIS and not request.stock_code.isdigit():
            request.broker = BrokerType.TOSS
        if request.broker is BrokerType.TOSS:
            rows = await _settings_map(session)
            order = await TossRestClient.from_settings_map(rows).place_order(request)
        else:
            request.stock_code = request.stock_code.zfill(6)
            order = await kis_client.place_order(request)
    except KISRestError as exc:
        return _error_response("KIS_ORDER_FAILED", str(exc), exc)
    except TossRestError as exc:
        return _error_response("TOSS_ORDER_FAILED", str(exc), exc)

    persistence = await _persist_trade_skeleton(session, order, request)
    if (
        request.broker is BrokerType.KIS
        and persistence.persisted
        and persistence.trade_id is not None
        and order.kis_order_no
    ):
        background_tasks.add_task(_schedule_order_tracking, persistence.trade_id)
    return OrderEnvelope(
        data=OrderEnvelopeData(order=order, trade_persistence=persistence),
        error=None,
    )


async def _persist_trade_skeleton(
    session: AsyncSession,
    order,
    request: OrderRequest,
) -> TradePersistResult:
    # This is intentionally a submission-side skeleton. The order tracker updates
    # it with broker fill state, actual price, fees, taxes, and fill timestamp.
    try:
        account_type = order.account_type or request.account_type
        await _ensure_account_row(session, account_type)
        trade = Trade(
            account_type=account_type.value,
            stock_code=order.stock_code,
            direction=order.direction.value,
            quantity=order.quantity,
            price=order.price or Decimal("0"),
            executed_at=order.accepted_at,
            kis_order_no=order.kis_order_no or order.broker_order_no,
            status="PENDING",
            submitted_at=order.accepted_at,
            filled_quantity=0,
            fees=Decimal("0"),
            taxes=Decimal("0"),
            raw_order=json.dumps(
                {
                    "broker": order.broker.value,
                    "account_id": order.account_id,
                    "raw": order.raw,
                },
                ensure_ascii=False,
                default=str,
            ),
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


async def _settings_map(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(select(Setting))
    return {row.key: row.value for row in result.scalars()}


def _error_response(code: str, message: str, exc: KISRestError | TossRestError) -> JSONResponse:
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
        if not position.name and position.stock_code and position.stock_code.isdigit()
    ]
    if not missing_codes:
        return portfolio

    names = await asyncio.to_thread(lookup_stock_names, missing_codes)
    for position in portfolio.positions:
        if not position.name:
            position.name = names.get(position.stock_code) or position.stock_code
    return portfolio


async def _enrich_position_prices(
    portfolio: PortfolioResponse,
    broker: BrokerType,
) -> PortfolioResponse:
    symbols = [
        position.stock_code
        for position in portfolio.positions
        if position.stock_code
        and (
            position.current_price is None
            or position.current_price <= Decimal("0")
        )
    ]

    for position in portfolio.positions:
        position.broker = broker
        if broker is BrokerType.KIS:
            position.account_type = portfolio.account_type
            position.currency = position.currency or "KRW"
            position.market_country = position.market_country or "KR"
            if position.stock_code.isdigit():
                position.stock_code = position.stock_code.zfill(6)
        else:
            position.account_id = portfolio.account_id
            position.currency = position.currency or (
                "KRW" if position.stock_code.isdigit() else "USD"
            )
            position.market_country = position.market_country or (
                "KR" if position.stock_code.isdigit() else "US"
            )

    if not symbols:
        return portfolio

    account_type = portfolio.account_type or settings.KIS_DEFAULT_ACCOUNT
    result = await fetch_current_quotes(
        broker=broker,
        symbols=symbols,
        account_type=account_type,
        account_id=portfolio.account_id,
    )
    quotes = {quote.symbol.upper(): quote for quote in result.quotes}
    for position in portfolio.positions:
        quote = quotes.get(position.stock_code.upper())
        if quote is None and position.stock_code.isdigit():
            quote = quotes.get(position.stock_code.zfill(6))
        if quote is None:
            continue
        position.current_price = quote.price
        position.currency = position.currency or quote.currency
        if position.purchase_amount is None:
            position.purchase_amount = position.avg_buy_price * Decimal(position.quantity)
        if position.evaluation_amount is None:
            position.evaluation_amount = quote.price * Decimal(position.quantity)
        if position.purchase_amount is not None:
            position.unrealized_pl = position.evaluation_amount - position.purchase_amount

    return portfolio


def _unified_response(
    portfolios: list[PortfolioResponse],
    errors: list[dict[str, object]],
    fx_rate: FxRate | None = None,
) -> UnifiedPortfolioResponse:
    accounts: list[AccountSummaryResponse] = []
    positions: list[UnifiedPositionResponse] = []

    total_value = Decimal("0")
    total_pl = Decimal("0")
    total_cost = Decimal("0")

    for portfolio in portfolios:
        summary = portfolio.summary
        account_value, account_cost, account_pl, cash_krw, cash_usd = _account_totals(
            portfolio,
            fx_rate,
        )
        account_cash = cash_krw or Decimal("0")
        account_pl_pct = _pct(account_pl, account_cost)

        total_value += account_value
        total_pl += account_pl
        total_cost += account_cost
        accounts.append(
            AccountSummaryResponse(
                broker=portfolio.broker,
                account_type=portfolio.account_type,
                account_id=portfolio.account_id,
                currency=summary.currency,
                total_value=account_value,
                cash_balance=account_cash,
                cash_krw=cash_krw,
                cash_usd=cash_usd,
                total_pl=account_pl,
                total_pl_pct=account_pl_pct,
            )
        )

        for position in portfolio.positions:
            stock_name = position.name or position.stock_code
            positions.append(
                UnifiedPositionResponse(
                    broker=portfolio.broker,
                    account_type=portfolio.account_type,
                    account_id=portfolio.account_id,
                    stock_code=position.stock_code,
                    name=stock_name,
                    stock_name=stock_name,
                    currency=position.currency,
                    market_country=position.market_country,
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
        fx_rate=fx_rate.rate if fx_rate is not None else None,
        fx_as_of=fx_rate.as_of if fx_rate is not None else None,
        accounts=accounts,
        positions=positions,
        errors=errors,
    )


async def _portfolio_fx_rate(
    portfolios: list[PortfolioResponse],
    errors: list[dict[str, object]],
) -> FxRate | None:
    needs_fx = any(
        portfolio.broker is BrokerType.TOSS
        or (portfolio.summary.cash_usd is not None and portfolio.summary.cash_usd != 0)
        or any((position.currency or "").upper() == "USD" for position in portfolio.positions)
        for portfolio in portfolios
    )
    if not needs_fx:
        return None
    try:
        return await get_fx_rate(base="USD", quote="KRW")
    except FxRateError as exc:
        errors.append(
            {
                "broker": BrokerType.TOSS.value,
                "source": "fx_rate",
                "message": str(exc),
            }
        )
        return None


def _account_totals(
    portfolio: PortfolioResponse,
    fx_rate: FxRate | None,
) -> tuple[Decimal, Decimal, Decimal, Decimal | None, Decimal | None]:
    summary = portfolio.summary
    cash_krw = summary.cash_krw
    if cash_krw is None and (summary.currency or "KRW").upper() == "KRW":
        cash_krw = summary.cash_amount
    cash_usd = summary.cash_usd

    if portfolio.broker is not BrokerType.TOSS:
        return (
            summary.total_evaluation_amount or Decimal("0"),
            summary.purchase_amount or Decimal("0"),
            summary.unrealized_pl or Decimal("0"),
            cash_krw,
            cash_usd,
        )

    stock_value = Decimal("0")
    stock_cost = Decimal("0")
    stock_pl = Decimal("0")
    for position in portfolio.positions:
        currency = (position.currency or _infer_position_currency(position.stock_code)).upper()
        quantity = Decimal(position.quantity)
        evaluation = position.evaluation_amount
        if evaluation is None and position.current_price is not None:
            evaluation = position.current_price * quantity
        purchase = position.purchase_amount
        if purchase is None:
            purchase = position.avg_buy_price * quantity
        profit_loss = position.unrealized_pl
        if profit_loss is None and evaluation is not None and purchase is not None:
            profit_loss = evaluation - purchase

        stock_value += _to_krw(evaluation, currency, fx_rate)
        stock_cost += _to_krw(purchase, currency, fx_rate)
        stock_pl += _to_krw(profit_loss, currency, fx_rate)

    account_value = stock_value + (cash_krw or Decimal("0"))
    if cash_usd is not None:
        account_value += _to_krw(cash_usd, "USD", fx_rate)
    return account_value, stock_cost, stock_pl, cash_krw, cash_usd


def _to_krw(amount: Decimal | None, currency: str, fx_rate: FxRate | None) -> Decimal:
    if amount is None:
        return Decimal("0")
    if currency.upper() == "USD":
        return amount * fx_rate.rate if fx_rate is not None else Decimal("0")
    return amount


def _infer_position_currency(symbol: str) -> str:
    return "KRW" if symbol.isdigit() else "USD"


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
