"""Intraday KOSPI200 heatmap snapshot cache."""

from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from backend.app.core.config import settings
from backend.app.services.kis.rest_client import KISCurrentPrice, KISRestClient
from research.universe.kospi200 import DEFAULT_CODES_FILE, get_kospi200
from shared.domain.account import AccountType

logger = logging.getLogger(__name__)


class MarketSession(StrEnum):
    PRE_MARKET = "PRE_MARKET"
    REGULAR = "REGULAR"
    AFTER_HOURS = "AFTER_HOURS"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class HeatmapSnapshotItem:
    code: str
    name: str | None
    current_price: float
    previous_close: float | None
    change_amount: float | None
    change_pct: float
    volume: int
    market_cap: float | None


@dataclass(frozen=True, slots=True)
class HeatmapSnapshot:
    market: str = "KOSPI"
    market_session: MarketSession = MarketSession.CLOSED
    updated_at: datetime | None = None
    source: str = "empty"
    items: dict[str, HeatmapSnapshotItem] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


_snapshot_lock = asyncio.Lock()
current_heatmap_data = HeatmapSnapshot()
_scheduler: AsyncIOScheduler | None = None


def get_market_session(now: datetime | None = None) -> MarketSession:
    """Return the Korean equity trading session for ``now``."""

    tz = ZoneInfo(settings.APSCHEDULER_TIMEZONE)
    current = now.astimezone(tz) if now else datetime.now(tz)
    if not is_korean_equity_business_day(current):
        return MarketSession.CLOSED

    current_time = current.time()
    pre_start = _parse_hhmm(settings.MARKET_SESSION_PRE_MARKET_START)
    pre_end = _parse_hhmm(settings.MARKET_SESSION_PRE_MARKET_END)
    regular_start = _parse_hhmm(settings.MARKET_SESSION_REGULAR_START)
    regular_end = _parse_hhmm(settings.MARKET_SESSION_REGULAR_END)
    after_start = _parse_hhmm(settings.MARKET_SESSION_AFTER_HOURS_START)
    after_end = _parse_hhmm(settings.MARKET_SESSION_AFTER_HOURS_END)

    if pre_start <= current_time <= pre_end:
        return MarketSession.PRE_MARKET
    if regular_start <= current_time < regular_end:
        return MarketSession.REGULAR
    if after_start <= current_time <= after_end:
        return MarketSession.AFTER_HOURS
    return MarketSession.CLOSED


def is_korean_equity_business_day(now: datetime | None = None) -> bool:
    """Best-effort Korean trading-day guard.

    The pykrx calendar path is used when available; if KRX is temporarily
    unreachable, we fall back to the deterministic weekday check so the API does
    not fail closed because of a data-vendor outage.
    """

    tz = ZoneInfo(settings.APSCHEDULER_TIMEZONE)
    current = now.astimezone(tz) if now else datetime.now(tz)
    if current.weekday() >= 5:
        return False
    return _is_krx_business_day_cached(current.date().isoformat())


def is_live_market_session(session: MarketSession | None = None) -> bool:
    session = session or get_market_session()
    return session in {
        MarketSession.PRE_MARKET,
        MarketSession.REGULAR,
        MarketSession.AFTER_HOURS,
    }


def get_current_heatmap_snapshot() -> HeatmapSnapshot:
    return current_heatmap_data


async def get_live_heatmap_snapshot(
    *,
    max_age: timedelta | None = None,
    refresh_if_stale: bool = True,
) -> HeatmapSnapshot:
    """Return the live snapshot, refreshing once when the cache is empty/stale."""

    snapshot = get_current_heatmap_snapshot()
    session = get_market_session()
    max_age = max_age or timedelta(minutes=settings.MARKET_SNAPSHOT_STALE_AFTER_MINUTES)
    if not is_live_market_session(session):
        return snapshot

    now = datetime.now(ZoneInfo(settings.APSCHEDULER_TIMEZONE))
    is_stale = (
        snapshot.updated_at is None
        or snapshot.market_session is MarketSession.CLOSED
        or now - snapshot.updated_at.astimezone(now.tzinfo) > max_age
    )
    if is_stale and refresh_if_stale:
        await refresh_current_heatmap_snapshot()
        snapshot = get_current_heatmap_snapshot()
    return snapshot


async def refresh_current_heatmap_snapshot() -> HeatmapSnapshot:
    """Fetch KOSPI200 current prices from KIS and replace the in-memory cache."""

    async with _snapshot_lock:
        session = get_market_session()
        now = datetime.now(ZoneInfo(settings.APSCHEDULER_TIMEZONE))
        if not is_live_market_session(session):
            _set_snapshot(
                HeatmapSnapshot(
                    market_session=session,
                    updated_at=now,
                    source="closed",
                    items={},
                    errors={},
                )
            )
            return get_current_heatmap_snapshot()

        account = settings.kis_account(settings.MARKET_SNAPSHOT_ACCOUNT_TYPE)
        if (
            not account.app_key.get_secret_value()
            or not account.app_secret.get_secret_value()
        ):
            snapshot = HeatmapSnapshot(
                market_session=session,
                updated_at=now,
                source="kis:credentials_missing",
                items={},
                errors={
                    "credentials": (
                        "MARKET_SNAPSHOT_ACCOUNT_TYPE credentials are not configured."
                    )
                },
            )
            _set_snapshot(snapshot)
            logger.warning(
                "skipped market snapshot refresh because %s credentials are missing",
                settings.MARKET_SNAPSHOT_ACCOUNT_TYPE.value,
            )
            return snapshot

        codes = _resolve_kospi200_codes(now)
        client = KISRestClient()
        semaphore = asyncio.Semaphore(settings.MARKET_SNAPSHOT_REQUEST_CONCURRENCY)
        items: dict[str, HeatmapSnapshotItem] = {}
        errors: dict[str, str] = {}

        async def fetch_one(code: str) -> None:
            async with semaphore:
                try:
                    quote = await client.get_current_price(
                        settings.MARKET_SNAPSHOT_ACCOUNT_TYPE,
                        code,
                    )
                    items[code] = _item_from_quote(quote)
                except Exception as exc:
                    errors[code] = str(exc)[:300]

        await asyncio.gather(*(fetch_one(code) for code in codes))

        snapshot = HeatmapSnapshot(
            market_session=session,
            updated_at=now,
            source="kis:inquire-price",
            items=dict(sorted(items.items())),
            errors=errors,
        )
        _set_snapshot(snapshot)
        logger.info(
            "updated intraday heatmap snapshot session=%s items=%s errors=%s",
            snapshot.market_session.value,
            len(snapshot.items),
            len(snapshot.errors),
        )
        return snapshot


def start_market_snapshot_scheduler() -> AsyncIOScheduler:
    """Start a 5-minute KOSPI200 snapshot scheduler for live market sessions."""

    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    timezone = ZoneInfo(settings.APSCHEDULER_TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=timezone)
    interval = settings.MARKET_SNAPSHOT_INTERVAL_MINUTES
    scheduler.add_job(
        refresh_current_heatmap_snapshot,
        OrTrigger(
            [
                CronTrigger(
                    day_of_week="mon-fri",
                    hour="8",
                    minute=f"0-50/{interval}",
                    timezone=timezone,
                ),
                CronTrigger(
                    day_of_week="mon-fri",
                    hour="9-14",
                    minute=f"*/{interval}",
                    timezone=timezone,
                ),
                CronTrigger(
                    day_of_week="mon-fri",
                    hour="15",
                    minute=f"0-59/{interval}",
                    timezone=timezone,
                ),
                CronTrigger(
                    day_of_week="mon-fri",
                    hour="16-19",
                    minute=f"*/{interval}",
                    timezone=timezone,
                ),
                CronTrigger(
                    day_of_week="mon-fri",
                    hour="20",
                    minute="0",
                    timezone=timezone,
                ),
            ]
        ),
        id="market_snapshot_refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if is_live_market_session():
        scheduler.add_job(
            refresh_current_heatmap_snapshot,
            id="market_snapshot_startup_refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone),
        )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "started market snapshot scheduler account=%s interval=%sm timezone=%s",
        settings.MARKET_SNAPSHOT_ACCOUNT_TYPE.value,
        settings.MARKET_SNAPSHOT_INTERVAL_MINUTES,
        settings.APSCHEDULER_TIMEZONE,
    )
    return scheduler


def stop_market_snapshot_scheduler(scheduler: AsyncIOScheduler | None = None) -> None:
    global _scheduler
    target = scheduler or _scheduler
    if target is not None and target.running:
        target.shutdown(wait=False)
    if target is _scheduler:
        _scheduler = None


def _set_snapshot(snapshot: HeatmapSnapshot) -> None:
    global current_heatmap_data
    current_heatmap_data = snapshot


def _resolve_kospi200_codes(now: datetime) -> list[str]:
    manual_codes = _read_codes_file(DEFAULT_CODES_FILE)
    if manual_codes:
        return manual_codes
    try:
        return get_kospi200(now.date(), allow_fallback=True)
    except Exception:
        logger.exception("failed to resolve KOSPI200 codes for market snapshot")
        return []


def _read_codes_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    return list(dict.fromkeys(re.findall(r"(?<!\d)\d{6}(?!\d)", text)))


def _item_from_quote(quote: KISCurrentPrice) -> HeatmapSnapshotItem:
    return HeatmapSnapshotItem(
        code=quote.stock_code,
        name=quote.name,
        current_price=_decimal_to_float(quote.current_price),
        previous_close=_optional_decimal_to_float(quote.previous_close),
        change_amount=_optional_decimal_to_float(quote.change_amount),
        change_pct=_decimal_to_float(quote.change_pct),
        volume=quote.volume,
        market_cap=_optional_decimal_to_float(quote.market_cap),
    )


def _decimal_to_float(value: Decimal) -> float:
    return float(value)


def _optional_decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _parse_hhmm(value: str) -> time:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        return time(int(hour_text), int(minute_text))
    except Exception:
        logger.warning("invalid market session time %r; falling back to 00:00", value)
        return time(0, 0)


@lru_cache(maxsize=512)
def _is_krx_business_day_cached(date_text: str) -> bool:
    try:
        from pykrx import stock

        yyyymmdd = date_text.replace("-", "")
        nearest = stock.get_nearest_business_day_in_a_week(yyyymmdd)
        return str(nearest) == yyyymmdd
    except Exception:
        return datetime.fromisoformat(date_text).weekday() < 5
