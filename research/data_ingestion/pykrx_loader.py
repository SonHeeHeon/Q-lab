"""pykrx-based OHLCV, index, and listed-stock loaders."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.exc import OperationalError
from sqlalchemy.dialects.sqlite import insert

os.environ.setdefault("MPLCONFIGDIR", str(Path("/private/tmp/qlab-mplconfig")))

from shared.db.models import MarketIndex, PriceDaily, Stock
from shared.db.session import research_session

MARKET_INDEX_TICKERS = {
    "KOSPI": "1001",
    "KOSDAQ": "2001",
}

FDR_INDEX_TICKERS = {
    "KOSPI": "KS11",
    "KOSDAQ": "KQ11",
}

SQLITE_LOCK_RETRY_ATTEMPTS = 8
SQLITE_LOCK_RETRY_BASE_SECONDS = 0.25
_DB_WRITE_LOCK = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class LoadResult:
    name: str
    requested: int
    inserted_or_ignored: int


async def update_universe(
    market: str,
    *,
    as_of: date,
    listed_at_default: date,
) -> LoadResult:
    """Upsert currently listed stock metadata for one KRX market."""

    market = market.upper()
    stock = _pykrx_stock()
    try:
        codes = await asyncio.to_thread(
            stock.get_market_ticker_list,
            _to_yyyymmdd(as_of),
            market,
        )
    except Exception as exc:
        print(f"[phase2:warn] pykrx ticker list failed for {market}: {exc}")
        codes = []
    rows = []
    for code in sorted({str(code).zfill(6) for code in codes}):
        name = await asyncio.to_thread(stock.get_market_ticker_name, code)
        rows.append(
            {
                "code": code,
                "name": name or code,
                "market": market,
                "sector": None,
                "industry": None,
                "listed_at": listed_at_default,
                "delisted_at": None,
                "is_delisted": False,
            }
        )

    await _upsert_stock_rows(rows)
    return LoadResult(name=f"stocks:{market}", requested=len(rows), inserted_or_ignored=len(rows))


async def ensure_stock_rows(
    codes: Iterable[str],
    *,
    market: str = "KOSPI",
    listed_at_default: date,
) -> LoadResult:
    stock = _pykrx_stock()
    rows = []
    for code in sorted({str(code).zfill(6) for code in codes}):
        try:
            name = await asyncio.to_thread(stock.get_market_ticker_name, code)
        except Exception:
            name = code
        rows.append(
            {
                "code": code,
                "name": name or code,
                "market": market,
                "sector": None,
                "industry": None,
                "listed_at": listed_at_default,
                "delisted_at": None,
                "is_delisted": False,
            }
        )
    await _upsert_stock_rows(rows)
    return LoadResult(name=f"stocks:{market}:selected", requested=len(rows), inserted_or_ignored=len(rows))


async def update_prices(
    codes: Iterable[str],
    *,
    start: date,
    end: date,
    concurrency: int = 4,
    sleep_seconds: float = 0.15,
) -> LoadResult:
    """Download adjusted daily OHLCV and insert into prices_daily."""

    semaphore = asyncio.Semaphore(concurrency)
    total_rows = 0

    async def load_one(code: str) -> int:
        stock = _pykrx_stock()
        async with semaphore:
            try:
                df = await asyncio.to_thread(
                    stock.get_market_ohlcv_by_date,
                    _to_yyyymmdd(start),
                    _to_yyyymmdd(end),
                    code,
                    "d",
                    True,
                )
            except Exception as exc:
                print(f"[phase2:warn] pykrx price failed for {code}: {exc}")
                df = await asyncio.to_thread(_fdr_price_frame, code, start, end)
            await asyncio.sleep(sleep_seconds)
        rows = _price_rows_from_frame(code, df)
        await _insert_ignore(PriceDaily, rows)
        return len(rows)

    for rows_count in await asyncio.gather(
        *(load_one(str(code).zfill(6)) for code in codes)
    ):
        total_rows += rows_count

    return LoadResult(name="prices_daily", requested=total_rows, inserted_or_ignored=total_rows)


async def update_market_index(
    index_code: str,
    *,
    start: date,
    end: date,
) -> LoadResult:
    """Download KOSPI/KOSDAQ daily close into market_index."""

    stock = _pykrx_stock()
    ticker = MARKET_INDEX_TICKERS[index_code.upper()]
    try:
        df = await asyncio.to_thread(
            stock.get_index_ohlcv_by_date,
            _to_yyyymmdd(start),
            _to_yyyymmdd(end),
            ticker,
            "d",
            False,
        )
    except Exception as exc:
        print(f"[phase2:warn] pykrx index failed for {index_code.upper()}: {exc}")
        df = await asyncio.to_thread(_fdr_index_frame, index_code.upper(), start, end)
    rows = []
    for row_date, row in df.iterrows():
        close = _pick(row, "종가", "Close", "close")
        if close is None:
            continue
        rows.append(
            {
                "index_code": index_code.upper(),
                "date": _to_date(row_date),
                "close": _to_decimal(close),
            }
        )
    await _insert_ignore(MarketIndex, rows)
    return LoadResult(name=f"market_index:{index_code.upper()}", requested=len(rows), inserted_or_ignored=len(rows))


async def update_market_indices(*, start: date, end: date) -> list[LoadResult]:
    return [
        await update_market_index("KOSPI", start=start, end=end),
        await update_market_index("KOSDAQ", start=start, end=end),
    ]


async def get_trading_days(start: date, end: date) -> list[date]:
    stock = _pykrx_stock()
    try:
        df = await asyncio.to_thread(
            stock.get_index_ohlcv_by_date,
            _to_yyyymmdd(start),
            _to_yyyymmdd(end),
            MARKET_INDEX_TICKERS["KOSPI"],
            "d",
            False,
        )
    except Exception:
        df = await asyncio.to_thread(_fdr_index_frame, "KOSPI", start, end)
    return [_to_date(idx) for idx in df.index]


async def _upsert_stock_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with _DB_WRITE_LOCK:
        await _with_sqlite_lock_retries(_upsert_stock_rows_once, rows)


async def _upsert_stock_rows_once(rows: list[dict[str, Any]]) -> None:
    async with research_session() as session:
        for chunk in _chunks(rows, _safe_insert_chunk_size(rows)):
            stmt = insert(Stock).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Stock.code],
                set_={
                    "name": stmt.excluded.name,
                    "market": stmt.excluded.market,
                    "sector": stmt.excluded.sector,
                    "industry": stmt.excluded.industry,
                },
            )
            await session.execute(stmt)
        await session.commit()


async def _insert_ignore(model: Any, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with _DB_WRITE_LOCK:
        await _with_sqlite_lock_retries(_insert_ignore_once, model, rows)


async def _insert_ignore_once(model: Any, rows: list[dict[str, Any]]) -> None:
    async with research_session() as session:
        for chunk in _chunks(rows, _safe_insert_chunk_size(rows)):
            stmt = insert(model).values(chunk).on_conflict_do_nothing()
            await session.execute(stmt)
        await session.commit()


async def _with_sqlite_lock_retries(operation: Any, *args: Any) -> None:
    for attempt in range(SQLITE_LOCK_RETRY_ATTEMPTS):
        try:
            await operation(*args)
            return
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            if attempt == SQLITE_LOCK_RETRY_ATTEMPTS - 1:
                raise
            delay = SQLITE_LOCK_RETRY_BASE_SECONDS * (2**attempt)
            print(
                "[phase2:warn] SQLite database is locked during research write; "
                f"retrying in {delay:.2f}s"
            )
            await asyncio.sleep(delay)


def _safe_insert_chunk_size(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 1
    column_count = max(1, len(rows[0]))
    return max(1, 900 // column_count)


def _chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _price_rows_from_frame(code: str, df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    if df is None or df.empty:
        return rows
    for row_date, row in df.iterrows():
        open_ = _pick(row, "시가", "Open", "open")
        high = _pick(row, "고가", "High", "high")
        low = _pick(row, "저가", "Low", "low")
        close = _pick(row, "종가", "Close", "close")
        volume = _pick(row, "거래량", "Volume", "volume")
        if any(value is None for value in (open_, high, low, close, volume)):
            continue
        rows.append(
            {
                "stock_code": code,
                "date": _to_date(row_date),
                "open": _to_decimal(open_),
                "high": _to_decimal(high),
                "low": _to_decimal(low),
                "close": _to_decimal(close),
                "volume": int(volume),
                "adj_close": _to_decimal(close),
            }
        )
    return rows


def _pick(row: pd.Series, *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _to_yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _to_date(value: Any) -> date:
    return pd.Timestamp(value).date()


def _to_decimal(value: Any) -> Decimal:
    return Decimal(str(value).replace(",", ""))


def _pykrx_stock():
    from pykrx import stock

    return stock


def _fdr_price_frame(code: str, start: date, end: date) -> pd.DataFrame:
    try:
        import FinanceDataReader as fdr

        return fdr.DataReader(code, start, end)
    except Exception as exc:
        print(f"[phase2:warn] FinanceDataReader price failed for {code}: {exc}")
        return pd.DataFrame()


def _fdr_index_frame(index_code: str, start: date, end: date) -> pd.DataFrame:
    try:
        import FinanceDataReader as fdr

        return fdr.DataReader(FDR_INDEX_TICKERS[index_code], start, end)
    except Exception as exc:
        print(f"[phase2:warn] FinanceDataReader index failed for {index_code}: {exc}")
        return pd.DataFrame()
