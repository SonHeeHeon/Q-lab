"""ETF price ingestion — expands the tradable/backtestable universe to
index/asset-class ETFs (자동매매 범위 증설).

KR ETFs are stored exactly like stocks (``stocks`` market='ETF' +
``prices_daily``), so momentum/flow factors, the backtest engine, the app's
search/detail, and KIS order flow all work on them unchanged. US ETFs go into
``stocks_us``/``prices_daily_us`` with exchange='ETF'.

KR source: pykrx (KRX 로그인 필요 — KRX_ID/KRX_PW). US source: yfinance.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date

import pandas as pd

from research.data_ingestion.pykrx_loader import (
    LoadResult,
    _insert_ignore,
    _price_rows_from_frame,
    _pykrx_stock,
    _to_yyyymmdd,
    _upsert_stock_rows,
)
from shared.db.models import PriceDaily
from shared.db.session import research_db_path

# Core KR ETF set: one liquid proxy per asset class (dual-momentum rotation)
# plus a few satellites. All listed on/before 2016 except where noted.
KR_CORE_ETFS: dict[str, str] = {
    "069500": "KODEX 200",              # KR large-cap equity
    "229200": "KODEX 코스닥150",         # KR growth/small-cap
    "133690": "TIGER 미국나스닥100",      # US growth equity (KRW)
    "143850": "TIGER 미국S&P500선물(H)",  # US broad equity (hedged)
    "132030": "KODEX 골드선물(H)",        # gold
    "148070": "KOSEF 국고채10년",         # KR long bond
    "114260": "KODEX 국고채3년",          # KR short bond (cash-like)
    "091160": "KODEX 반도체",             # sector satellite
    "261240": "KODEX 미국달러선물",       # USD (2016-12 listing)
    "114800": "KODEX 인버스",             # KR equity inverse (hedge)
}

# Classic GTAA-style US ETF set (all long history, USD).
US_CORE_ETFS: dict[str, str] = {
    "SPY": "SPDR S&P 500",
    "QQQ": "Invesco QQQ (Nasdaq-100)",
    "IWM": "iShares Russell 2000",
    "EFA": "iShares MSCI EAFE",
    "EEM": "iShares MSCI Emerging Markets",
    "TLT": "iShares 20+ Year Treasury",
    "IEF": "iShares 7-10 Year Treasury",
    "GLD": "SPDR Gold Shares",
    "DBC": "Invesco DB Commodity",
    "VNQ": "Vanguard Real Estate",
    # 광범위 대형주
    "VOO": "Vanguard S&P 500",
    "VTI": "Vanguard Total US Market",
    "DIA": "SPDR Dow Jones",
    # 섹터 SPDR (XLRE는 VNQ와 겹쳐 제외)
    "XLK": "Technology Select Sector",
    "XLF": "Financial Select Sector",
    "XLE": "Energy Select Sector",
    "XLV": "Health Care Select Sector",
    "XLI": "Industrial Select Sector",
    "XLP": "Consumer Staples Select Sector",
    "XLY": "Consumer Discretionary Select Sector",
    "XLU": "Utilities Select Sector",
    "XLB": "Materials Select Sector",
    "XLC": "Communication Services Select Sector",
    # 팩터/스타일
    "SCHD": "Schwab US Dividend Equity",
    "VIG": "Vanguard Dividend Appreciation",
    "MTUM": "iShares MSCI USA Momentum",
    "QUAL": "iShares MSCI USA Quality",
    "VTV": "Vanguard Value",
    "VUG": "Vanguard Growth",
    # 채권
    "AGG": "iShares Core US Aggregate Bond",
    "LQD": "iShares IG Corporate Bond",
    "HYG": "iShares High Yield Corporate",
    "SHY": "iShares 1-3 Year Treasury",
}


async def update_kr_etf_prices(
    *,
    start: date,
    end: date,
    codes: dict[str, str] | None = None,
    concurrency: int = 4,
    sleep_seconds: float = 0.15,
) -> LoadResult:
    """Download KR ETF daily OHLCV into prices_daily (+ stocks market='ETF')."""

    etfs = codes or KR_CORE_ETFS
    semaphore = asyncio.Semaphore(concurrency)
    total_rows = 0

    async def load_one(code: str, name: str) -> int:
        pykrx_stock = _pykrx_stock()
        async with semaphore:
            try:
                df = await asyncio.to_thread(
                    pykrx_stock.get_etf_ohlcv_by_date,
                    _to_yyyymmdd(start),
                    _to_yyyymmdd(end),
                    code,
                )
            except Exception as exc:
                print(f"[etf:warn] pykrx ETF price failed for {code}: {exc}")
                return 0
            await asyncio.sleep(sleep_seconds)
        rows = _price_rows_from_frame(code, df)
        if not rows:
            return 0
        # prices_daily.stock_code has an FK to stocks.code (and the session
        # runs with foreign_keys=ON), so the stocks row MUST exist first.
        await _upsert_stock_rows(
            [
                {
                    "code": code,
                    "name": name,
                    "market": "ETF",
                    "sector": None,
                    "industry": None,
                    "listed_at": rows[0]["date"],
                    "delisted_at": None,
                    "is_delisted": False,
                }
            ]
        )
        await _insert_ignore(PriceDaily, rows)
        return len(rows)

    for count in await asyncio.gather(
        *(load_one(code, name) for code, name in etfs.items())
    ):
        total_rows += count

    return LoadResult(
        name="etf_kr_prices", requested=total_rows, inserted_or_ignored=total_rows
    )


async def update_us_etf_prices(
    *,
    start: date,
    end: date,
    tickers: dict[str, str] | None = None,
) -> LoadResult:
    """Download US ETF closes into prices_daily_us (+ stocks_us exchange='ETF')."""

    etfs = tickers or US_CORE_ETFS
    close_f, adj_f = await asyncio.to_thread(_download_yf_prices, list(etfs), start, end)
    total = 0
    with sqlite3.connect(research_db_path) as conn:
        _ensure_us_dedup_indexes(conn)
        for ticker, name in etfs.items():
            if ticker not in close_f.columns:
                continue
            adj_series = adj_f[ticker] if ticker in adj_f.columns else close_f[ticker]
            rows = _us_price_rows(ticker, close_f[ticker], adj_series)
            conn.executemany(_UPSERT_US_PRICE, rows)
            conn.execute(
                "INSERT OR IGNORE INTO stocks_us"
                " (ticker, name, exchange, sector, industry, currency,"
                "  listed_at, delisted_at, is_delisted)"
                " VALUES (?,?,?,?,?,?,?,?,0)",
                (
                    ticker,
                    name,
                    "ETF",
                    None,
                    None,
                    "USD",
                    rows[0][1] if rows else None,
                    None,
                ),
            )
            total += len(rows)
        conn.commit()
    return LoadResult(
        name="etf_us_prices", requested=total, inserted_or_ignored=total
    )


def _download_yf_prices(
    tickers: list[str], start: date, end: date
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (close, adj_close) frames keyed by ticker. adj_close carries the
    dividend+split adjustment — dropping it (the old code stored raw close as
    both) understates total return badly for distribution-heavy ETFs (TLT/AGG/
    SCHD), which is exactly what momentum/absolute-momentum gates read."""
    import warnings

    import yfinance as yf

    warnings.filterwarnings("ignore")
    data = yf.download(
        tickers,
        start=start.isoformat(),
        end=end.isoformat(),
        progress=False,
        auto_adjust=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        return data["Close"], data["Adj Close"]
    close = data[["Close"]].rename(columns={"Close": tickers[0]})
    adj = data[["Adj Close"]].rename(columns={"Adj Close": tickers[0]})
    return close, adj


def _us_price_rows(ticker: str, close: pd.Series, adj: pd.Series) -> list[tuple]:
    rows: list[tuple] = []
    for idx, value in close.items():
        if value is None or pd.isna(value) or float(value) <= 0:
            continue
        day = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        price = round(float(value), 6)
        adj_value = adj.get(idx)
        adj_price = round(float(adj_value), 6) if adj_value is not None and not pd.isna(adj_value) else price
        # OHLC beyond close isn't needed by the engine (it reads close only).
        rows.append((ticker, day, price, price, price, price, 0, adj_price, "USD"))
    return rows


async def update_us_prices_incremental(*, start: date, end: date) -> LoadResult:
    """Incremental close update for EVERY ticker already in stocks_us
    (NASDAQ100 stocks + US ETFs) via one batched yfinance download.

    Keeps prices_daily_us from going stale — before this, US prices only
    advanced when the bulk download script was run by hand.
    """
    with sqlite3.connect(research_db_path) as conn:
        _ensure_us_dedup_indexes(conn)
        tickers = [
            row[0]
            for row in conn.execute(
                "SELECT ticker FROM stocks_us WHERE is_delisted = 0 ORDER BY ticker"
            )
        ]
    if not tickers:
        return LoadResult(name="us_prices", requested=0, inserted_or_ignored=0)

    close_f, adj_f = await asyncio.to_thread(_download_yf_prices, tickers, start, end)
    total = 0
    with sqlite3.connect(research_db_path) as conn:
        for ticker in tickers:
            if ticker not in close_f.columns:
                continue
            adj_series = adj_f[ticker] if ticker in adj_f.columns else close_f[ticker]
            rows = _us_price_rows(ticker, close_f[ticker], adj_series)
            conn.executemany(_UPSERT_US_PRICE, rows)
            total += len(rows)
        conn.commit()
    return LoadResult(name="us_prices", requested=total, inserted_or_ignored=total)


# UPSERT (not INSERT OR IGNORE) so re-running re-adjusts historical adj_close
# after a new split/dividend — IGNORE would freeze stale adjustments forever.
_UPSERT_US_PRICE = (
    "INSERT INTO prices_daily_us"
    " (ticker, date, open, high, low, close, volume, adj_close, currency)"
    " VALUES (?,?,?,?,?,?,?,?,?)"
    " ON CONFLICT(ticker, date) DO UPDATE SET"
    "   open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,"
    "   volume=excluded.volume, adj_close=excluded.adj_close, currency=excluded.currency"
)


def _ensure_us_dedup_indexes(conn: sqlite3.Connection) -> None:
    """The ad-hoc US tables ship without PKs — add unique indexes so
    INSERT OR IGNORE is genuinely idempotent."""
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_us_ticker_date"
        " ON prices_daily_us(ticker, date)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_stocks_us_ticker"
        " ON stocks_us(ticker)"
    )
