"""Stock detail API for research-driven frontend views."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.schemas.portfolio import ApiEnvelope, PositionResponse
from backend.app.services.brokers.base import BrokerAccountRef
from backend.app.services.kis.rest_client import KISRestClient
from backend.app.services.market_data.quotes import fetch_current_quotes
from backend.app.services.toss.rest_client import TossRestClient
from research.factors.common import normalize_code
from research.factors.quality import calculate_roa, calculate_roe
from research.factors.value import calculate_pbr, calculate_per
from shared.domain.account import AccountType, BrokerType
from shared.db.models import Setting
from shared.db.session import ServiceSessionLocal, research_db_path, service_db_path

router = APIRouter(prefix="/api/stocks", tags=["stocks"])
logger = logging.getLogger(__name__)


class PricePoint(BaseModel):
    date: Date
    close: float
    volume: int


class Candle(BaseModel):
    date: Date
    open: float
    high: float
    low: float
    close: float
    volume: int


class StockSearchResult(BaseModel):
    symbol: str
    code: str
    name: str | None
    korean_name: str | None = None
    market_country: Literal["KR", "US"]
    broker: BrokerType
    market: str | None
    sector: str | None
    industry: str | None
    currency: str


class CurrentQuoteBrief(BaseModel):
    price: Decimal | None = None
    currency: str | None = None
    timestamp: datetime | str | None = None
    change_pct: Decimal | None = None
    volume: int | None = None
    error: str | None = None


class HoldingInfo(BaseModel):
    is_holding: bool
    quantity: int
    latest_trade_at: str | None = None


class WatchlistInfo(BaseModel):
    is_watchlisted: bool
    entries: list[dict[str, Any]]


class StockDetailResponse(BaseModel):
    code: str
    symbol: str
    name: str | None
    korean_name: str | None = None
    market_country: Literal["KR", "US"] = "KR"
    broker: BrokerType = BrokerType.KIS
    market: str | None
    sector: str | None
    industry: str | None
    currency: str = "KRW"
    as_of: Date | None
    latest_price: PricePoint | None
    current_quote: CurrentQuoteBrief | None = None
    factors: dict[str, float | None]
    factor_ranks: dict[str, float | None]
    price_history: list[PricePoint]
    holding: HoldingInfo
    watchlist: WatchlistInfo
    local_activity: dict[str, Any]


@router.get("/search", response_model=ApiEnvelope[list[StockSearchResult]])
async def search_stocks(
    q: str = Query(min_length=1),
    market: Literal["ALL", "KR", "US"] = Query(default="ALL"),
    limit: int = Query(default=20, ge=1, le=100),
) -> ApiEnvelope[list[StockSearchResult]]:
    results = await asyncio.to_thread(_search_stocks, q, market, limit)
    return ApiEnvelope(data=results, error=None)


@router.get(
    "/{market_country}/{symbol}/history",
    response_model=ApiEnvelope[list[Candle]],
)
async def get_price_history(
    market_country: Literal["KR", "US"],
    symbol: str,
    interval: Literal["day", "week", "month", "year"] = Query(default="day"),
    count: int = Query(default=120, ge=1, le=2000),
    before: Date | None = None,
) -> ApiEnvelope[list[Candle]]:
    normalized_market = market_country.upper()
    normalized_symbol = _normalize_symbol(symbol, normalized_market)
    candles = await asyncio.to_thread(
        _build_candles,
        normalized_symbol,
        normalized_market,
        interval,
        count,
        before,
    )
    return ApiEnvelope(data=candles, error=None)


@router.get("/{market_country}/{symbol}", response_model=ApiEnvelope[StockDetailResponse])
async def get_stock_detail_by_market(
    market_country: Literal["KR", "US"],
    symbol: str,
    as_of: Date | None = Query(default=None),
    history_days: int = Query(default=250, ge=1, le=2500),
) -> ApiEnvelope[StockDetailResponse]:
    normalized_market = market_country.upper()
    normalized_symbol = _normalize_symbol(symbol, normalized_market)
    response = await asyncio.to_thread(
        _build_stock_detail,
        normalized_symbol,
        as_of,
        history_days,
        normalized_market,
    )
    response.current_quote = await _fetch_current_quote(
        normalized_symbol,
        normalized_market,
    )
    response.holding = await _augment_holding(
        normalized_symbol,
        normalized_market,
        response,
    )
    return ApiEnvelope(data=response, error=None)


@router.get("/{code}", response_model=ApiEnvelope[StockDetailResponse])
async def get_stock_detail(
    code: str,
    as_of: Date | None = Query(default=None),
    history_days: int = Query(default=250, ge=1, le=2500),
) -> ApiEnvelope[StockDetailResponse]:
    normalized_code = normalize_code(code)
    response = await asyncio.to_thread(
        _build_stock_detail,
        normalized_code,
        as_of,
        history_days,
        "KR",
    )
    response.current_quote = await _fetch_current_quote(normalized_code, "KR")
    response.holding = await _augment_holding(normalized_code, "KR", response)
    return ApiEnvelope(data=response, error=None)


def _build_stock_detail(
    symbol: str,
    as_of: Date | None,
    history_days: int,
    market_country: str = "KR",
) -> StockDetailResponse:
    if market_country == "US":
        return _build_us_stock_detail(symbol, as_of, history_days)

    code = normalize_code(symbol)
    selected_date = as_of or _latest_price_date_kr(code)
    meta = _stock_meta_kr(code)
    history = _price_history_kr(code, selected_date, history_days)
    latest_price = history[-1] if history else None
    factor_values = _factor_values(code, selected_date)
    factor_ranks = _factor_ranks(code, selected_date, meta.get("market"))
    local_activity = _local_activity(code)
    return StockDetailResponse(
        code=code,
        symbol=code,
        name=meta.get("name"),
        market_country="KR",
        broker=BrokerType.KIS,
        market=meta.get("market"),
        sector=meta.get("sector"),
        industry=meta.get("industry"),
        currency="KRW",
        as_of=selected_date,
        latest_price=latest_price,
        factors=factor_values,
        factor_ranks=factor_ranks,
        price_history=history,
        holding=_holding_info(code),
        watchlist=_watchlist_info(code),
        local_activity=local_activity,
    )


def _build_us_stock_detail(
    symbol: str,
    as_of: Date | None,
    history_days: int,
) -> StockDetailResponse:
    ticker = symbol.strip().upper()
    selected_date = as_of or _latest_price_date_us(ticker)
    meta = _stock_meta_us(ticker)
    history = _price_history_us(ticker, selected_date, history_days)
    latest_price = history[-1] if history else None
    factor_values = _factor_values(ticker, selected_date)
    factor_ranks = _factor_ranks_us(ticker, selected_date)
    return StockDetailResponse(
        code=ticker,
        symbol=ticker,
        name=meta.get("name"),
        korean_name=meta.get("korean_name"),
        market_country="US",
        broker=BrokerType.TOSS,
        market=meta.get("market"),
        sector=meta.get("sector"),
        industry=meta.get("industry"),
        currency=meta.get("currency") or "USD",
        as_of=selected_date,
        latest_price=latest_price,
        factors=factor_values,
        factor_ranks=factor_ranks,
        price_history=history,
        holding=_holding_info(ticker),
        watchlist=_watchlist_info(ticker),
        local_activity=_local_activity(ticker),
    )


async def _fetch_current_quote(
    symbol: str,
    market_country: str,
) -> CurrentQuoteBrief:
    broker = BrokerType.TOSS if market_country == "US" else BrokerType.KIS
    try:
        result = await fetch_current_quotes(
            broker=broker,
            symbols=[symbol],
            account_type=AccountType.PAPER,
        )
    except Exception as exc:
        return CurrentQuoteBrief(error=str(exc)[:500])

    if result.quotes:
        quote = result.quotes[0]
        return CurrentQuoteBrief(
            price=quote.price,
            currency=quote.currency,
            timestamp=quote.timestamp,
            change_pct=quote.change_pct,
            volume=quote.volume,
        )
    return CurrentQuoteBrief(error=result.errors.get(symbol) or "quote not found")


def _search_stocks(
    query: str,
    market: str,
    limit: int,
) -> list[StockSearchResult]:
    normalized_query = query.strip().upper()
    if not normalized_query:
        return []

    results: list[StockSearchResult] = []
    if market in {"ALL", "KR"}:
        results.extend(_search_kr_stocks(normalized_query, limit))
    if market in {"ALL", "US"}:
        results.extend(_search_us_stocks(normalized_query, limit))
    return results[:limit]


def _search_kr_stocks(query: str, limit: int) -> list[StockSearchResult]:
    code_query = query.zfill(6) if query.isdigit() else query
    like = f"%{query}%"
    code_like = f"%{code_query}%"
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            """
            SELECT code, name, market, sector, industry
            FROM stocks
            WHERE code LIKE ?
               OR UPPER(name) LIKE ?
            ORDER BY
                CASE WHEN code = ? THEN 0
                     WHEN UPPER(name) = ? THEN 1
                     WHEN code LIKE ? THEN 2
                     ELSE 3 END,
                market,
                code
            LIMIT ?
            """,
            [code_like, like, code_query, query, f"{code_query}%", limit],
        ).fetchall()
    return [
        StockSearchResult(
            symbol=str(code).zfill(6),
            code=str(code).zfill(6),
            name=name,
            market_country="KR",
            broker=BrokerType.KIS,
            market=row_market,
            sector=sector,
            industry=industry,
            currency="KRW",
        )
        for code, name, row_market, sector, industry in rows
    ]


def _search_us_stocks(query: str, limit: int) -> list[StockSearchResult]:
    if not _table_exists(research_db_path, "stocks_us"):
        return []
    like = f"%{query}%"
    # `korean_name` is added by a parallel migration and may not exist yet; detect
    # it so Korean-language search works once the column lands, without crashing
    # before it does. LIKE is case-insensitive for ASCII and Hangul has no case,
    # so the already-normalized query still matches Korean names correctly.
    has_korean = _column_exists(research_db_path, "stocks_us", "korean_name")
    select_cols = "ticker, name, exchange, sector, industry, currency"
    where_clause = "UPPER(ticker) LIKE ?\n               OR UPPER(name) LIKE ?"
    params: list[object] = [like, like]
    if has_korean:
        select_cols += ", korean_name"
        where_clause += "\n               OR korean_name LIKE ?"
        params.append(like)
    params += [query, f"{query}%", query, limit]
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT {select_cols}
            FROM stocks_us
            WHERE {where_clause}
            ORDER BY
                CASE WHEN UPPER(ticker) = ? THEN 0
                     WHEN UPPER(ticker) LIKE ? THEN 1
                     WHEN UPPER(name) = ? THEN 2
                     ELSE 3 END,
                ticker
            LIMIT ?
            """,
            params,
        ).fetchall()
    results: list[StockSearchResult] = []
    for row in rows:
        if has_korean:
            ticker, name, exchange, sector, industry, currency, korean_name = row
        else:
            ticker, name, exchange, sector, industry, currency = row
            korean_name = None
        results.append(
            StockSearchResult(
                symbol=str(ticker).upper(),
                code=str(ticker).upper(),
                name=name,
                korean_name=korean_name,
                market_country="US",
                broker=BrokerType.TOSS,
                market=exchange,
                sector=sector,
                industry=industry,
                currency=currency or "USD",
            )
        )
    return results


def _stock_meta_kr(code: str) -> dict[str, str | None]:
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute(
            """
            SELECT name, market, sector, industry
            FROM stocks
            WHERE code = ?
            """,
            [code],
        ).fetchone()
    if row is None:
        return {"name": None, "market": None, "sector": None, "industry": None}
    name, market, sector, industry = row
    return {
        "name": name,
        "market": market,
        "sector": sector,
        "industry": industry,
    }


def _stock_meta_us(ticker: str) -> dict[str, str | None]:
    if not _table_exists(research_db_path, "stocks_us"):
        return {
            "name": None,
            "korean_name": None,
            "market": None,
            "sector": None,
            "industry": None,
            "currency": "USD",
        }
    # `korean_name` is populated by a parallel migration; include it only when the
    # column already exists so this stays independently testable.
    has_korean = _column_exists(research_db_path, "stocks_us", "korean_name")
    select_cols = "name, exchange, sector, industry, currency"
    if has_korean:
        select_cols += ", korean_name"
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute(
            f"""
            SELECT {select_cols}
            FROM stocks_us
            WHERE ticker = ?
            """,
            [ticker],
        ).fetchone()
    if row is None:
        return {
            "name": None,
            "korean_name": None,
            "market": None,
            "sector": None,
            "industry": None,
            "currency": "USD",
        }
    if has_korean:
        name, exchange, sector, industry, currency, korean_name = row
    else:
        name, exchange, sector, industry, currency = row
        korean_name = None
    return {
        "name": name,
        "korean_name": korean_name,
        "market": exchange,
        "sector": sector,
        "industry": industry,
        "currency": currency,
    }


def _latest_price_date_kr(code: str) -> Date | None:
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM prices_daily WHERE stock_code = ?",
            [code],
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return Date.fromisoformat(str(row[0]))


def _latest_price_date_us(ticker: str) -> Date | None:
    if not _table_exists(research_db_path, "prices_daily_us"):
        return None
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM prices_daily_us WHERE ticker = ?",
            [ticker],
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return Date.fromisoformat(str(row[0]))


def _price_history_kr(
    code: str,
    as_of: Date | None,
    limit: int,
) -> list[PricePoint]:
    if as_of is None:
        return []
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            """
            SELECT date, COALESCE(adj_close, close) AS close, volume
            FROM prices_daily
            WHERE stock_code = ?
              AND date <= ?
            ORDER BY date DESC
            LIMIT ?
            """,
            [code, as_of.isoformat(), limit],
        ).fetchall()
    points = [
        PricePoint(date=Date.fromisoformat(str(day)), close=float(close), volume=int(volume))
        for day, close, volume in rows
    ]
    return list(reversed(points))


def _price_history_us(
    ticker: str,
    as_of: Date | None,
    limit: int,
) -> list[PricePoint]:
    if as_of is None or not _table_exists(research_db_path, "prices_daily_us"):
        return []
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            """
            SELECT date, COALESCE(adj_close, close) AS close, volume
            FROM prices_daily_us
            WHERE ticker = ?
              AND date <= ?
            ORDER BY date DESC
            LIMIT ?
            """,
            [ticker, as_of.isoformat(), limit],
        ).fetchall()
    points = [
        PricePoint(date=Date.fromisoformat(str(day)), close=float(close), volume=int(volume))
        for day, close, volume in rows
    ]
    return list(reversed(points))


# Approximate calendar days per aggregation bucket. Used only to bound how many
# daily rows to fetch; the last `count` fully-formed buckets are returned so the
# extra buffer (see `_build_candles`) absorbs any partial oldest bucket.
_INTERVAL_DAY_FACTOR = {"day": 1, "week": 7, "month": 31, "year": 366}


def _build_candles(
    symbol: str,
    market_country: str,
    interval: str,
    count: int,
    before: Date | None,
) -> list[Candle]:
    if market_country == "US":
        as_of = before or _latest_price_date_us(symbol)
    else:
        as_of = before or _latest_price_date_kr(symbol)
    if as_of is None:
        return []
    factor = _INTERVAL_DAY_FACTOR.get(interval, 1)
    # Fetch a little more than strictly needed so the oldest returned bucket is
    # complete; we then slice to the most recent `count` buckets.
    day_limit = count * factor + factor * 3 + 10
    rows = _fetch_daily_ohlc(symbol, market_country, as_of, day_limit)
    if not rows:
        return []
    candles = _aggregate_candles(rows, interval)
    return candles[-count:]


def _fetch_daily_ohlc(
    symbol: str,
    market_country: str,
    as_of: Date,
    day_limit: int,
) -> list[tuple[Date, float, float, float, float, int]]:
    """Return daily OHLC rows (ascending, date <= as_of) as (date, o, h, l, c, v).

    Both tables carry real open/high/low/close/volume, so we read them directly.
    Should a US source ever be close-only (open=high=low=close, volume=0) the
    null-to-close fallback below still yields correct flat-bodied candles.
    """
    if market_country == "US":
        if not _table_exists(research_db_path, "prices_daily_us"):
            return []
        table, code_column = "prices_daily_us", "ticker"
    else:
        table, code_column = "prices_daily", "stock_code"

    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT date, open, high, low, close, volume
            FROM {table}
            WHERE {code_column} = ?
              AND date <= ?
            ORDER BY date DESC
            LIMIT ?
            """,
            [symbol, as_of.isoformat(), day_limit],
        ).fetchall()
    out: list[tuple[Date, float, float, float, float, int]] = []
    for day, open_, high, low, close, volume in rows:
        if close is None:
            continue
        close_value = float(close)
        out.append(
            (
                Date.fromisoformat(str(day)),
                float(open_) if open_ is not None else close_value,
                float(high) if high is not None else close_value,
                float(low) if low is not None else close_value,
                close_value,
                int(volume or 0),
            )
        )
    return list(reversed(out))


def _bucket_key(day: Date, interval: str) -> object:
    if interval == "week":
        iso = day.isocalendar()
        return (iso[0], iso[1])
    if interval == "month":
        return (day.year, day.month)
    if interval == "year":
        return day.year
    return day.toordinal()


def _aggregate_candles(
    rows: list[tuple[Date, float, float, float, float, int]],
    interval: str,
) -> list[Candle]:
    candles: list[Candle] = []
    current_key: object = None
    current: Candle | None = None
    for day, open_, high, low, close, volume in rows:
        key = _bucket_key(day, interval)
        if current is None or key != current_key:
            if current is not None:
                candles.append(current)
            current_key = key
            current = Candle(
                date=day,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        else:
            current.high = max(current.high, high)
            current.low = min(current.low, low)
            current.close = close
            current.volume += volume
            current.date = day
    if current is not None:
        candles.append(current)
    return candles


def _factor_values(code: str, as_of: Date | None) -> dict[str, float | None]:
    if as_of is None:
        return {"PER": None, "PBR": None, "ROE": None, "ROA": None}
    values = {
        "PER": calculate_per([code], as_of=as_of).get(code),
        "PBR": calculate_pbr([code], as_of=as_of).get(code),
        "ROE": calculate_roe([code], as_of=as_of).get(code),
        "ROA": calculate_roa([code], as_of=as_of).get(code),
    }
    return {key: _float_or_none(value) for key, value in values.items()}


def _factor_ranks(code: str, as_of: Date | None, market: str | None) -> dict[str, float | None]:
    if as_of is None or market is None:
        return {"PER": None, "PBR": None, "ROE": None}
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            """
            SELECT code
            FROM stocks
            WHERE market = ?
              AND listed_at <= ?
              AND (delisted_at IS NULL OR delisted_at > ?)
            """,
            [market, as_of.isoformat(), as_of.isoformat()],
        ).fetchall()
    codes = [str(row[0]).zfill(6) for row in rows]
    if code not in codes:
        codes.append(code)
    result: dict[str, float | None] = {}
    for factor_name, series in {
        "PER": calculate_per(codes, as_of=as_of),
        "PBR": calculate_pbr(codes, as_of=as_of),
        "ROE": calculate_roe(codes, as_of=as_of),
    }.items():
        ranks = series.rank(pct=True, ascending=factor_name in {"PER", "PBR"})
        result[factor_name] = _float_or_none(ranks.get(code))
    return result


def _factor_ranks_us(ticker: str, as_of: Date | None) -> dict[str, float | None]:
    if as_of is None or not _table_exists(research_db_path, "stocks_us"):
        return {"PER": None, "PBR": None, "ROE": None}
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            """
            SELECT ticker
            FROM stocks_us
            WHERE (listed_at IS NULL OR listed_at <= ?)
              AND (delisted_at IS NULL OR delisted_at > ?)
            """,
            [as_of.isoformat(), as_of.isoformat()],
        ).fetchall()
    tickers = [str(row[0]).upper() for row in rows]
    if ticker not in tickers:
        tickers.append(ticker)
    result: dict[str, float | None] = {}
    for factor_name, series in {
        "PER": calculate_per(tickers, as_of=as_of),
        "PBR": calculate_pbr(tickers, as_of=as_of),
        "ROE": calculate_roe(tickers, as_of=as_of),
    }.items():
        ranks = series.rank(pct=True, ascending=factor_name in {"PER", "PBR"})
        result[factor_name] = _float_or_none(ranks.get(ticker))
    return result


def _holding_info(symbol: str) -> HoldingInfo:
    path = Path(service_db_path)
    if not path.exists():
        return HoldingInfo(is_holding=False, quantity=0)
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            """
            SELECT direction, quantity, filled_quantity, status, executed_at, filled_at
            FROM trades
            WHERE UPPER(stock_code) = UPPER(?)
            ORDER BY COALESCE(filled_at, executed_at) ASC
            """,
            [symbol],
        ).fetchall()
    quantity = 0
    latest_trade_at: str | None = None
    for direction, qty, filled_qty, status, executed_at, filled_at in rows:
        status_text = str(status or "").upper()
        effective_qty = int(filled_qty or 0) if int(filled_qty or 0) > 0 else int(qty or 0)
        if status_text in {"CANCELED", "CANCELLED", "REJECTED"}:
            continue
        if str(direction).upper() == "BUY":
            quantity += effective_qty
        elif str(direction).upper() == "SELL":
            quantity -= effective_qty
        latest_trade_at = str(filled_at or executed_at or latest_trade_at)
    quantity = max(quantity, 0)
    return HoldingInfo(
        is_holding=quantity > 0,
        quantity=quantity,
        latest_trade_at=latest_trade_at,
    )


# Broker balance calls are async and can be slow or fail; keep the live lookup
# tightly bounded so stock detail never blocks or breaks on broker issues.
_LIVE_HOLDING_TIMEOUT_SECONDS = 3.0

# Short TTL cache for merged broker positions, keyed by "KR"/"US". Browsing
# several stock details must not re-hit the balance endpoints each time (Toss
# rate-limits after a couple of rapid calls). value = (monotonic_ts, positions).
_POSITIONS_CACHE: dict[str, tuple[float, list["PositionResponse"]]] = {}
_POSITIONS_CACHE_TTL_SECONDS = 60.0


async def _augment_holding(
    symbol: str,
    market_country: str,
    response: StockDetailResponse,
) -> HoldingInfo:
    """Merge live broker positions into the trades-table holding result.

    The local `trades` table only knows about orders placed through this app, so a
    stock the user holds via KIS/Toss but never traded here shows as '미보유'. We
    consult live broker positions and, when a matching position is found, treat the
    broker as authoritative for `is_holding`/`quantity`. On ANY failure (network,
    timeout, missing credentials) we fall back to the existing trades result.
    """
    live = await _live_holding_info(symbol, market_country, response.name)
    if live is None:
        return response.holding
    return HoldingInfo(
        is_holding=True,
        quantity=live.quantity,
        latest_trade_at=response.holding.latest_trade_at,
    )


async def _live_holding_info(
    symbol: str,
    market_country: str,
    meta_name: str | None,
) -> HoldingInfo | None:
    """Return a live-broker HoldingInfo, or None to fall back to trades."""
    try:
        return await asyncio.wait_for(
            _fetch_live_holding(symbol, market_country, meta_name),
            timeout=_LIVE_HOLDING_TIMEOUT_SECONDS,
        )
    except Exception:
        return None


async def _fetch_live_holding(
    symbol: str,
    market_country: str,
    meta_name: str | None,
) -> HoldingInfo | None:
    positions = await _live_positions(market_country)
    for position in positions:
        if _position_matches(position, symbol, market_country, meta_name):
            quantity = int(position.quantity or 0)
            if quantity > 0:
                return HoldingInfo(is_holding=True, quantity=quantity)
    return None


async def _live_positions(market_country: str) -> list[PositionResponse]:
    """Live positions across every broker that could custody this stock.

    Toss custodies BOTH US and KR equities (a user's Toss account can hold
    005930 삼성전자 as well as LRCX), so Toss is always queried. KIS holds KR
    equities natively across PAPER/REAL/ISA, so it is additionally queried for
    KR stocks. Querying only one broker per market missed KR-in-Toss holdings.

    A short in-process TTL cache fronts the broker balance calls: browsing
    several stock details in a row must not re-hit them each time — Toss's
    balance endpoint rate-limits after a couple of rapid calls, and a swallowed
    rate-limit would silently drop back to the trades ledger and re-show
    '미보유' for a Toss-only holding. The cache is populated only when a broker
    leg actually succeeds, so a transient failure isn't cached as "no holdings".
    Each broker leg is exception-tolerant (logged, never raised); the caller
    wraps this in a timeout and falls back to the trades ledger on empty.
    """
    key = "KR" if market_country == "KR" else "US"
    now = time.monotonic()
    cached = _POSITIONS_CACHE.get(key)
    if cached is not None and now - cached[0] < _POSITIONS_CACHE_TTL_SECONDS:
        return cached[1]

    positions: list[PositionResponse] = []
    any_success = False

    # Toss — US + KR both possible. Mirror portfolio.py's balance path.
    try:
        rows = await _settings_map_standalone()
        toss = TossRestClient.from_settings_map(rows)
        if toss.is_configured:
            account_id = rows.get("toss_account_seq") or (
                str(settings.TOSS_ACCOUNT_SEQ)
                if settings.TOSS_ACCOUNT_SEQ is not None
                else None
            )
            portfolio = await toss.get_balance(
                BrokerAccountRef(broker=BrokerType.TOSS, account_id=account_id)
            )
            positions.extend(portfolio.positions)
            any_success = True
    except Exception as exc:  # rate limit / decode / network — never break detail
        logger.warning("live positions: Toss balance failed: %s", exc)

    # KIS — KR equities across PAPER/REAL/ISA (US isn't held natively in KIS).
    if market_country == "KR":
        try:
            kis = KISRestClient()
            results = await asyncio.gather(
                *(kis.get_balance(account_type) for account_type in AccountType),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("live positions: KIS balance failed: %s", result)
                else:
                    positions.extend(result.positions)
                    any_success = True
        except Exception as exc:
            logger.warning("live positions: KIS balance failed: %s", exc)

    # Only cache real answers — never cache an all-failed empty list, or a
    # transient rate-limit would pin '미보유' for the whole TTL window.
    if any_success:
        _POSITIONS_CACHE[key] = (now, positions)
    return positions


def _position_matches(
    position: PositionResponse,
    symbol: str,
    market_country: str,
    meta_name: str | None,
) -> bool:
    pos_code = (position.stock_code or "").strip().upper()
    target = symbol.strip().upper()
    if not pos_code:
        return False
    if market_country == "KR":
        return pos_code.zfill(6) == target.zfill(6)
    # US: match on ticker/symbol case-insensitively. The current PositionResponse
    # does not expose the Toss ISIN, so fall back to a name match for tolerance
    # when Toss returns a slightly different symbol.
    if pos_code == target:
        return True
    if (
        meta_name
        and position.name
        and position.name.strip().lower() == meta_name.strip().lower()
    ):
        return True
    return False


async def _settings_map_standalone() -> dict[str, str]:
    async with ServiceSessionLocal() as session:
        result = await session.execute(select(Setting))
        return {row.key: row.value for row in result.scalars()}


def _watchlist_info(symbol: str) -> WatchlistInfo:
    path = Path(service_db_path)
    if not path.exists():
        return WatchlistInfo(is_watchlisted=False, entries=[])
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.category_id, c.name, e.reason, e.added_at
            FROM watchlist_entries e
            JOIN watchlist_categories c ON c.id = e.category_id
            WHERE UPPER(e.stock_code) = UPPER(?)
            ORDER BY e.added_at DESC, e.id DESC
            """,
            [symbol],
        ).fetchall()
    entries = [
        {
            "id": int(entry_id),
            "category_id": int(category_id),
            "category_name": category_name,
            "reason": reason,
            "added_at": added_at,
        }
        for entry_id, category_id, category_name, reason, added_at in rows
    ]
    return WatchlistInfo(is_watchlisted=bool(entries), entries=entries)


def _local_activity(code: str) -> dict[str, Any]:
    path = Path(service_db_path)
    if not path.exists():
        return {"trade_count": 0, "latest_trade_at": None, "latest_journal_id": None}
    with sqlite3.connect(path) as conn:
        trade_row = conn.execute(
            """
            SELECT COUNT(*), MAX(executed_at)
            FROM trades
            WHERE stock_code = ?
            """,
            [code],
        ).fetchone()
        journal_row = conn.execute(
            """
            SELECT tj.id
            FROM trade_journal tj
            JOIN trades t ON t.id = tj.trade_id
            WHERE t.stock_code = ?
            ORDER BY tj.created_at DESC
            LIMIT 1
            """,
            [code],
        ).fetchone()
    return {
        "trade_count": int(trade_row[0] or 0) if trade_row else 0,
        "latest_trade_at": trade_row[1] if trade_row else None,
        "latest_journal_id": int(journal_row[0]) if journal_row else None,
    }


def _normalize_symbol(value: str, market_country: str) -> str:
    stripped = value.strip().upper()
    if market_country == "KR":
        return normalize_code(stripped)
    return stripped


def _table_exists(path: Path, table_name: str) -> bool:
    if not Path(path).exists():
        return False
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            [table_name],
        ).fetchone()
    return row is not None


def _column_exists(path: Path, table_name: str, column_name: str) -> bool:
    if not _table_exists(path, table_name):
        return False
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    return column_name in columns


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return result
