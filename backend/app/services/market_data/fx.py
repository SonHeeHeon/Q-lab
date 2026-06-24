"""Foreign-exchange helpers shared by API and portfolio aggregation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.services.toss.rest_client import TossRestClient, TossRestError
from shared.db.models import Setting
from shared.db.session import service_session


class FxRateError(RuntimeError):
    """Raised when an FX quote cannot be fetched from the configured provider."""


@dataclass(frozen=True, slots=True)
class FxRate:
    base: str
    quote: str
    rate: Decimal
    mid_rate: Decimal
    as_of: datetime
    change_type: str


_FX_CACHE_TTL = timedelta(seconds=60)
_fx_cache: dict[tuple[str, str], tuple[datetime, FxRate]] = {}
_fx_lock = asyncio.Lock()


async def get_fx_rate(
    *,
    base: str = "USD",
    quote: str = "KRW",
    ttl: timedelta = _FX_CACHE_TTL,
) -> FxRate:
    """Return a cached Toss FX quote.

    Toss documents the exchange-rate endpoint as a 1-minute reference quote, so
    successful responses are memoized for roughly that window. Failed lookups are
    intentionally not cached so operators can fix credentials and retry.
    """

    base = base.strip().upper()
    quote = quote.strip().upper()
    if base == quote:
        raise FxRateError("base and quote must be different currencies.")
    if {base, quote} != {"USD", "KRW"}:
        raise FxRateError(f"Unsupported FX pair: {base}/{quote}")

    key = (base, quote)
    now = _now()
    cached = _fx_cache.get(key)
    if cached is not None:
        fetched_at, fx_rate = cached
        if now - fetched_at < ttl:
            return fx_rate

    async with _fx_lock:
        now = _now()
        cached = _fx_cache.get(key)
        if cached is not None:
            fetched_at, fx_rate = cached
            if now - fetched_at < ttl:
                return fx_rate

        client = await _configured_toss_client()
        try:
            quote_response = await client.get_exchange_rate(
                base_currency=base,
                quote_currency=quote,
            )
        except TossRestError as exc:
            raise FxRateError(f"Toss FX lookup failed: {exc}") from exc

        fx_rate = FxRate(
            base=quote_response.base_currency,
            quote=quote_response.quote_currency,
            rate=quote_response.rate,
            mid_rate=quote_response.mid_rate,
            as_of=quote_response.valid_from,
            change_type=quote_response.change_type,
        )
        _fx_cache[key] = (_now(), fx_rate)
        return fx_rate


async def _configured_toss_client() -> TossRestClient:
    async with service_session() as session:
        result = await session.execute(select(Setting))
        rows = {row.key: row.value for row in result.scalars()}

    client = TossRestClient.from_settings_map(rows)
    if not client.is_configured:
        raise FxRateError("Toss credentials are not configured.")
    return client


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.APSCHEDULER_TIMEZONE))
