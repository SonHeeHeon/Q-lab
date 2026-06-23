"""Broker-neutral current quote helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.services.kis.rest_client import KISRestClient
from backend.app.services.toss.rest_client import TossRestClient
from shared.db.models import Setting
from shared.db.session import service_session
from shared.domain.account import AccountType, BrokerType


@dataclass(frozen=True, slots=True)
class CurrentQuote:
    broker: BrokerType
    symbol: str
    price: Decimal
    currency: str
    timestamp: datetime | str | None
    change_pct: Decimal | None = None
    volume: int | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class QuoteFetchResult:
    quotes: list[CurrentQuote]
    errors: dict[str, str]


async def fetch_current_quotes(
    *,
    broker: BrokerType,
    symbols: list[str],
    account_type: AccountType = AccountType.PAPER,
    account_id: str | None = None,
) -> QuoteFetchResult:
    normalized_symbols = _normalize_symbols(symbols, broker)
    if broker is BrokerType.KIS:
        return await _fetch_kis_quotes(normalized_symbols, account_type=account_type)
    if broker is BrokerType.TOSS:
        return await _fetch_toss_quotes(normalized_symbols, account_id=account_id)
    raise ValueError(f"Unsupported broker: {broker}")


async def _fetch_kis_quotes(
    symbols: list[str],
    *,
    account_type: AccountType,
) -> QuoteFetchResult:
    client = KISRestClient()
    quotes: list[CurrentQuote] = []
    errors: dict[str, str] = {}
    now = datetime.now(ZoneInfo(settings.APSCHEDULER_TIMEZONE))

    for symbol in symbols:
        if not symbol.isdigit():
            errors[symbol] = "KIS quote symbols must be 6-digit Korean stock codes."
            continue
        try:
            quote = await client.get_current_price(account_type, symbol)
            quotes.append(
                CurrentQuote(
                    broker=BrokerType.KIS,
                    symbol=quote.stock_code,
                    price=quote.current_price,
                    currency="KRW",
                    timestamp=now,
                    change_pct=quote.change_pct,
                    volume=quote.volume,
                    raw=quote.raw,
                )
            )
        except Exception as exc:
            errors[symbol] = str(exc)[:500]

    return QuoteFetchResult(quotes=quotes, errors=errors)


async def _fetch_toss_quotes(
    symbols: list[str],
    *,
    account_id: str | None,
) -> QuoteFetchResult:
    async with service_session() as session:
        result = await session.execute(select(Setting))
        rows = {row.key: row.value for row in result.scalars()}

    client = TossRestClient.from_settings_map(rows)
    quotes: list[CurrentQuote] = []
    errors: dict[str, str] = {}

    try:
        broker_quotes = await client.get_current_prices(symbols)
    except Exception as exc:
        return QuoteFetchResult(
            quotes=[],
            errors={symbol: str(exc)[:500] for symbol in symbols},
        )

    by_symbol = {quote.symbol.upper(): quote for quote in broker_quotes}
    for symbol in symbols:
        quote = by_symbol.get(symbol.upper())
        if quote is None:
            errors[symbol] = "Toss quote not found."
            continue
        quotes.append(
            CurrentQuote(
                broker=BrokerType.TOSS,
                symbol=quote.symbol,
                price=quote.last_price,
                currency=quote.currency or _infer_currency(symbol),
                timestamp=quote.timestamp,
                change_pct=_decimal_from_raw(quote.raw or {}, "changePct", "changeRate"),
                volume=_int_from_raw(quote.raw or {}, "volume", "accumulatedVolume"),
                raw=quote.raw,
            )
        )

    return QuoteFetchResult(quotes=quotes, errors=errors)


def _normalize_symbols(symbols: list[str], broker: BrokerType) -> list[str]:
    normalized: list[str] = []
    for symbol in symbols:
        text = str(symbol).strip().upper()
        if not text:
            continue
        if broker is BrokerType.KIS and text.isdigit():
            text = text.zfill(6)
        normalized.append(text)
    return list(dict.fromkeys(normalized))


def _infer_currency(symbol: str) -> str:
    return "KRW" if symbol.isdigit() else "USD"


def _decimal_from_raw(raw: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            try:
                return Decimal(str(value).replace(",", ""))
            except Exception:
                return None
    return None


def _int_from_raw(raw: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            try:
                return int(Decimal(str(value).replace(",", "")))
            except Exception:
                return None
    return None
