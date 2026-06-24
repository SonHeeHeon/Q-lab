"""Stock detail API for research-driven frontend views."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.market_data.quotes import fetch_current_quotes
from research.factors.common import normalize_code
from research.factors.quality import calculate_roa, calculate_roe
from research.factors.value import calculate_pbr, calculate_per
from shared.domain.account import AccountType, BrokerType
from shared.db.session import research_db_path, service_db_path

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


class PricePoint(BaseModel):
    date: Date
    close: float
    volume: int


class StockSearchResult(BaseModel):
    symbol: str
    code: str
    name: str | None
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
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            """
            SELECT ticker, name, exchange, sector, industry, currency
            FROM stocks_us
            WHERE UPPER(ticker) LIKE ?
               OR UPPER(name) LIKE ?
            ORDER BY
                CASE WHEN UPPER(ticker) = ? THEN 0
                     WHEN UPPER(ticker) LIKE ? THEN 1
                     WHEN UPPER(name) = ? THEN 2
                     ELSE 3 END,
                ticker
            LIMIT ?
            """,
            [like, like, query, f"{query}%", query, limit],
        ).fetchall()
    return [
        StockSearchResult(
            symbol=str(ticker).upper(),
            code=str(ticker).upper(),
            name=name,
            market_country="US",
            broker=BrokerType.TOSS,
            market=exchange,
            sector=sector,
            industry=industry,
            currency=currency or "USD",
        )
        for ticker, name, exchange, sector, industry, currency in rows
    ]


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
            "market": None,
            "sector": None,
            "industry": None,
            "currency": "USD",
        }
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute(
            """
            SELECT name, exchange, sector, industry, currency
            FROM stocks_us
            WHERE ticker = ?
            """,
            [ticker],
        ).fetchone()
    if row is None:
        return {
            "name": None,
            "market": None,
            "sector": None,
            "industry": None,
            "currency": "USD",
        }
    name, exchange, sector, industry, currency = row
    return {
        "name": name,
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
