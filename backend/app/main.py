"""FastAPI application entry point."""

from __future__ import annotations

import logging
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging.handlers import TimedRotatingFileHandler

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.alerts import router as alerts_router
from backend.app.api.backtest import router as backtest_router
from backend.app.api.heatmap import router as heatmap_router
from backend.app.api.portfolio import router as portfolio_router
from backend.app.api.principles import router as principles_router
from backend.app.api.quant import router as quant_router
from backend.app.api.quotes import router as quotes_api_router
from backend.app.api.settings import router as settings_router
from backend.app.api.screener import router as screener_router
from backend.app.api.stocks import router as stocks_router
from backend.app.api.system import automation_router, router as system_router
from backend.app.api.trade_journal import router as trade_journal_router
from backend.app.api.watchlist import router as watchlist_router
from backend.app.core.config import settings
from backend.app.services.alerts.monitor import AlertMonitorService
from backend.app.services.batch.scheduler import start_batch_scheduler, stop_batch_scheduler
from backend.app.schemas.portfolio import ApiEnvelope, ApiError
from backend.app.services.kis.market_snapshot import (
    start_market_snapshot_scheduler,
    stop_market_snapshot_scheduler,
)
from backend.app.services.kis.order_tracker import OrderTrackerService
from backend.app.services.kis.risk_manager import PortfolioRiskManager
from backend.app.services.kis.ws_client import QuoteTick
from backend.app.services.kis.ws_client import KISWebSocketClient
from backend.app.ws.quotes import quote_manager, router as quotes_router
from backend.app.ws.quotes import set_upstream_client
from shared.db.session import research_engine, service_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _configure_logging()

    kis_ws_client: KISWebSocketClient | None = None
    batch_scheduler = None
    market_snapshot_scheduler = None
    order_tracker: OrderTrackerService | None = None
    risk_manager: PortfolioRiskManager | None = None
    risk_subscription_task: asyncio.Task[None] | None = None
    alert_monitor: AlertMonitorService | None = None

    if settings.RISK_MANAGER_AUTOSTART:
        risk_manager = PortfolioRiskManager()
        try:
            await risk_manager.refresh_positions()
            app.state.risk_manager = risk_manager
            logger.info(
                "started risk manager account=%s mock=%s threshold=%s codes=%s",
                risk_manager.account_type.value,
                settings.RISK_MANAGER_IS_MOCK,
                settings.RISK_MANAGER_STOP_LOSS_PCT,
                sorted(risk_manager.tracked_codes),
            )
        except Exception:
            logger.exception("risk manager startup failed; continuing without it")
            risk_manager = None

    async def handle_quote_tick(tick: QuoteTick) -> None:
        await quote_manager.broadcast_tick(tick)
        if risk_manager is not None:
            await risk_manager.handle_tick(tick)

    if settings.KIS_WS_AUTOSTART:
        kis_ws_client = KISWebSocketClient(
            settings.KIS_DEFAULT_ACCOUNT,
            on_tick=handle_quote_tick,
        )
        risk_codes = risk_manager.tracked_codes if risk_manager else set()
        await kis_ws_client.subscribe(
            sorted(set(settings.kis_ws_default_codes) | risk_codes)
        )
        kis_ws_client.start()
        set_upstream_client(kis_ws_client)
        app.state.kis_ws_client = kis_ws_client
        if risk_manager is not None:
            risk_subscription_task = asyncio.create_task(
                _reconcile_risk_subscriptions(kis_ws_client, risk_manager),
                name="portfolio-guard-subscription-reconciler",
            )
        logger.info(
            "started KIS websocket client for %s with codes=%s",
            settings.KIS_DEFAULT_ACCOUNT.value,
            settings.kis_ws_default_codes,
        )
    elif risk_manager is not None:
        logger.warning(
            "risk manager is enabled but KIS_WS_AUTOSTART=false; "
            "no ticks will be monitored"
        )

    if settings.BATCH_SCHEDULER_AUTOSTART:
        batch_scheduler = start_batch_scheduler()
        app.state.batch_scheduler = batch_scheduler

    if settings.MARKET_SNAPSHOT_AUTOSTART:
        market_snapshot_scheduler = start_market_snapshot_scheduler()
        app.state.market_snapshot_scheduler = market_snapshot_scheduler

    if settings.ORDER_TRACKER_AUTOSTART:
        order_tracker = OrderTrackerService()
        order_tracker.start()
        app.state.order_tracker = order_tracker

    if settings.ALERT_MONITOR_AUTOSTART:
        alert_monitor = AlertMonitorService()
        alert_monitor.start()
        app.state.alert_monitor = alert_monitor
        logger.info(
            "started alert monitor interval=%ss mock_orders=%s",
            settings.ALERT_MONITOR_INTERVAL_SECONDS,
            settings.ALERT_ORDER_IS_MOCK,
        )

    try:
        yield
    finally:
        set_upstream_client(None)
        if alert_monitor is not None:
            await alert_monitor.stop()
        if order_tracker is not None:
            await order_tracker.stop()
        stop_market_snapshot_scheduler(market_snapshot_scheduler)
        stop_batch_scheduler(batch_scheduler)
        if kis_ws_client is not None:
            await kis_ws_client.stop()
        if risk_subscription_task is not None:
            risk_subscription_task.cancel()
            try:
                await risk_subscription_task
            except asyncio.CancelledError:
                pass
        await service_engine.dispose()
        await research_engine.dispose()


app = FastAPI(title="Q-Lab API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    _request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    envelope = ApiEnvelope(
        data=None,
        error=ApiError(
            code="HTTP_ERROR",
            message=message,
            details=exc.detail if isinstance(exc.detail, dict) else None,
        ),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope.model_dump(mode="json"),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    envelope = ApiEnvelope(
        data=None,
        error=ApiError(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details={"errors": exc.errors()},
        ),
    )
    return JSONResponse(status_code=422, content=envelope.model_dump(mode="json"))


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error", exc_info=exc)
    envelope = ApiEnvelope(
        data=None,
        error=ApiError(
            code="INTERNAL_SERVER_ERROR",
            message="Internal server error",
            details=None,
        ),
    )
    return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))


app.include_router(backtest_router)
app.include_router(heatmap_router)
app.include_router(alerts_router)
app.include_router(portfolio_router)
app.include_router(principles_router)
app.include_router(quant_router)
app.include_router(quotes_api_router)
app.include_router(settings_router)
app.include_router(stocks_router)
app.include_router(screener_router)
app.include_router(system_router)
app.include_router(automation_router)
app.include_router(trade_journal_router)
app.include_router(watchlist_router)
app.include_router(quotes_router)


async def _reconcile_risk_subscriptions(
    kis_ws_client: KISWebSocketClient,
    risk_manager: PortfolioRiskManager,
) -> None:
    risk_subscribed_codes = set(risk_manager.tracked_codes)
    while True:
        await asyncio.sleep(settings.RISK_MANAGER_POSITION_REFRESH_SECONDS)
        try:
            latest_codes = await risk_manager.refresh_positions()
            to_subscribe = latest_codes - risk_subscribed_codes
            to_unsubscribe = (
                risk_subscribed_codes
                - latest_codes
                - set(settings.kis_ws_default_codes)
            )
            if to_subscribe:
                await kis_ws_client.subscribe(to_subscribe)
            if to_unsubscribe:
                await kis_ws_client.unsubscribe(to_unsubscribe)
            risk_subscribed_codes = set(latest_codes)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("risk manager subscription reconciliation failed")


def _configure_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=level)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    log_dir = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "backend.log"
    existing_paths = {
        getattr(handler, "baseFilename", None)
        for handler in root_logger.handlers
        if isinstance(handler, TimedRotatingFileHandler)
    }
    if str(log_path) in existing_paths:
        return

    file_handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        interval=1,
        backupCount=settings.LOG_BACKUP_DAYS,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root_logger.addHandler(file_handler)
