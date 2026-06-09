"""Download NASDAQ universe data into US-specific research tables."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _bootstrap_ssl_certificates() -> None:
    try:
        import certifi
    except Exception:
        return

    ca_file = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", ca_file)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_file)


_bootstrap_ssl_certificates()

import yfinance as yf
from dotenv import load_dotenv

from shared.db.session import research_db_path

NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"


@dataclass(frozen=True, slots=True)
class USStock:
    ticker: str
    name: str
    exchange: str = "NASDAQ"
    sector: str | None = None
    industry: str | None = None
    currency: str = "USD"


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    args = _parse_args()
    since = args.since or date.today() - timedelta(days=365 * args.years)
    until = args.until or date.today()
    db_path = args.db_path or research_db_path

    print(f"[us-ingest] universe={args.universe} since={since} until={until}")
    stocks = _resolve_universe(args)
    if args.max_tickers:
        stocks = stocks[: args.max_tickers]
        print(f"[us-ingest] max-tickers applied: {len(stocks)}")
    if not stocks:
        raise RuntimeError("No US tickers resolved.")

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _create_us_tables(conn)
        _upsert_stocks(conn, stocks)
        conn.commit()

        if not args.skip_prices:
            rows = _download_prices(
                conn,
                [stock.ticker for stock in stocks],
                since=since,
                until=until,
                sleep_seconds=args.sleep,
            )
            print(f"[us-ingest] prices_daily_us rows upserted={rows}")

        if not args.skip_financials:
            rows = _download_financials(
                conn,
                [stock.ticker for stock in stocks],
                sleep_seconds=args.sleep,
            )
            print(f"[us-ingest] financials_us rows upserted={rows}")

    print("[us-ingest] done")


def _resolve_universe(args: argparse.Namespace) -> list[USStock]:
    if args.tickers_file is not None:
        return [USStock(ticker=ticker, name=ticker) for ticker in _load_tickers_file(args.tickers_file)]
    if args.universe == "NASDAQ100":
        return _fetch_nasdaq100_members()
    raise ValueError(f"Unsupported US universe: {args.universe}")


def _fetch_nasdaq100_members() -> list[USStock]:
    try:
        import certifi
        import requests

        response = requests.get(
            NASDAQ100_URL,
            headers={"User-Agent": "Q-Lab/1.0 NASDAQ100 downloader"},
            timeout=20,
            verify=certifi.where(),
        )
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
    except Exception as exc:
        raise RuntimeError(f"NASDAQ100 constituent lookup failed: {exc}") from exc

    for table in tables:
        if table.empty:
            continue
        normalized_columns = {str(column).strip().lower(): column for column in table.columns}
        ticker_col = normalized_columns.get("ticker") or normalized_columns.get("symbol")
        name_col = normalized_columns.get("company") or normalized_columns.get("security")
        if ticker_col is None:
            continue
        sector_col = (
            normalized_columns.get("gics sector")
            or normalized_columns.get("sector")
        )
        industry_col = (
            normalized_columns.get("gics sub-industry")
            or normalized_columns.get("industry")
        )
        stocks: list[USStock] = []
        for _, row in table.iterrows():
            ticker = _normalize_ticker(row[ticker_col])
            if not ticker:
                continue
            stocks.append(
                USStock(
                    ticker=ticker,
                    name=str(row[name_col]).strip() if name_col is not None else ticker,
                    sector=_optional_text(row[sector_col]) if sector_col is not None else None,
                    industry=_optional_text(row[industry_col]) if industry_col is not None else None,
                )
            )
        if len(stocks) >= 90:
            return sorted(stocks, key=lambda item: item.ticker)

    raise RuntimeError("NASDAQ100 constituent table was not found in the source page.")


def _create_us_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stocks_us (
            ticker TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            exchange TEXT NOT NULL DEFAULT 'NASDAQ',
            sector TEXT,
            industry TEXT,
            currency TEXT NOT NULL DEFAULT 'USD',
            listed_at DATE,
            delisted_at DATE,
            is_delisted INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS prices_daily_us (
            ticker TEXT NOT NULL,
            date DATE NOT NULL,
            open NUMERIC NOT NULL,
            high NUMERIC NOT NULL,
            low NUMERIC NOT NULL,
            close NUMERIC NOT NULL,
            volume INTEGER NOT NULL DEFAULT 0,
            adj_close NUMERIC,
            currency TEXT NOT NULL DEFAULT 'USD',
            PRIMARY KEY (ticker, date),
            FOREIGN KEY (ticker) REFERENCES stocks_us(ticker)
        );

        CREATE TABLE IF NOT EXISTS financials_us (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            fiscal_period DATE NOT NULL,
            disclosed_at DATE NOT NULL,
            revenue NUMERIC,
            operating_income NUMERIC,
            net_income NUMERIC,
            total_assets NUMERIC,
            total_equity NUMERIC,
            eps NUMERIC,
            bps NUMERIC,
            currency TEXT NOT NULL DEFAULT 'USD',
            UNIQUE (ticker, fiscal_period),
            FOREIGN KEY (ticker) REFERENCES stocks_us(ticker)
        );

        CREATE INDEX IF NOT EXISTS ix_prices_daily_us_ticker_date
            ON prices_daily_us (ticker, date);
        CREATE INDEX IF NOT EXISTS ix_financials_us_ticker_disclosed
            ON financials_us (ticker, disclosed_at);
        """
    )


def _upsert_stocks(conn: sqlite3.Connection, stocks: list[USStock]) -> None:
    conn.executemany(
        """
        INSERT INTO stocks_us (
            ticker, name, exchange, sector, industry, currency, is_delisted
        )
        VALUES (?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(ticker) DO UPDATE SET
            name = excluded.name,
            exchange = excluded.exchange,
            sector = excluded.sector,
            industry = excluded.industry,
            currency = excluded.currency,
            is_delisted = 0
        """,
        [
            (
                stock.ticker,
                stock.name or stock.ticker,
                stock.exchange,
                stock.sector,
                stock.industry,
                stock.currency,
            )
            for stock in stocks
        ],
    )


def _download_prices(
    conn: sqlite3.Connection,
    tickers: Iterable[str],
    *,
    since: date,
    until: date,
    sleep_seconds: float,
) -> int:
    total = 0
    end_exclusive = until + timedelta(days=1)
    for ticker in tickers:
        try:
            frame = yf.Ticker(ticker).history(
                start=since.isoformat(),
                end=end_exclusive.isoformat(),
                interval="1d",
                auto_adjust=False,
            )
        except Exception as exc:
            print(f"[us-ingest:warn] yfinance price failed for {ticker}: {exc}")
            frame = pd.DataFrame()

        rows = _price_rows(ticker, frame)
        if rows:
            conn.executemany(
                """
                INSERT INTO prices_daily_us (
                    ticker, date, open, high, low, close, volume, adj_close, currency
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'USD')
                ON CONFLICT(ticker, date) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    adj_close = excluded.adj_close,
                    currency = excluded.currency
                """,
                rows,
            )
            conn.commit()
        total += len(rows)
        print(f"[us-ingest] prices:{ticker}: rows={len(rows)}")
        time.sleep(sleep_seconds)
    return total


def _download_financials(
    conn: sqlite3.Connection,
    tickers: Iterable[str],
    *,
    sleep_seconds: float,
) -> int:
    total = 0
    for ticker in tickers:
        try:
            ticker_obj = yf.Ticker(ticker)
            income = _frame_or_empty(ticker_obj, "quarterly_financials")
            balance = _frame_or_empty(ticker_obj, "quarterly_balance_sheet")
            info = _safe_info(ticker_obj)
        except Exception as exc:
            print(f"[us-ingest:warn] yfinance financials failed for {ticker}: {exc}")
            time.sleep(sleep_seconds)
            continue

        rows = _financial_rows(ticker, income, balance, info)
        if rows:
            conn.executemany(
                """
                INSERT INTO financials_us (
                    ticker, fiscal_period, disclosed_at, revenue, operating_income,
                    net_income, total_assets, total_equity, eps, bps, currency
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD')
                ON CONFLICT(ticker, fiscal_period) DO UPDATE SET
                    disclosed_at = excluded.disclosed_at,
                    revenue = excluded.revenue,
                    operating_income = excluded.operating_income,
                    net_income = excluded.net_income,
                    total_assets = excluded.total_assets,
                    total_equity = excluded.total_equity,
                    eps = excluded.eps,
                    bps = excluded.bps,
                    currency = excluded.currency
                """,
                rows,
            )
            conn.commit()
        total += len(rows)
        print(f"[us-ingest] financials:{ticker}: rows={len(rows)}")
        time.sleep(sleep_seconds)
    return total


def _price_rows(ticker: str, frame: pd.DataFrame) -> list[tuple[Any, ...]]:
    if frame is None or frame.empty:
        return []
    rows: list[tuple[Any, ...]] = []
    for row_date, row in frame.iterrows():
        open_ = _float_or_none(row.get("Open"))
        high = _float_or_none(row.get("High"))
        low = _float_or_none(row.get("Low"))
        close = _float_or_none(row.get("Close"))
        if any(value is None for value in (open_, high, low, close)):
            continue
        volume = _int_or_zero(row.get("Volume"))
        adj_close = _float_or_none(row.get("Adj Close")) or close
        rows.append(
            (
                ticker,
                pd.Timestamp(row_date).date().isoformat(),
                open_,
                high,
                low,
                close,
                volume,
                adj_close,
            )
        )
    return rows


def _financial_rows(
    ticker: str,
    income: pd.DataFrame,
    balance: pd.DataFrame,
    info: dict[str, Any],
) -> list[tuple[Any, ...]]:
    fiscal_periods = sorted(
        {
            parsed
            for frame in (income, balance)
            for column in frame.columns
            if not frame.empty
            if (parsed := _date_from_column(column)) is not None
        }
    )
    shares_outstanding = _float_or_none(info.get("sharesOutstanding"))
    fallback_eps = _float_or_none(info.get("trailingEps"))
    fallback_bps = _float_or_none(info.get("bookValue"))

    rows: list[tuple[Any, ...]] = []
    for fiscal_period in fiscal_periods:
        revenue = _metric(income, fiscal_period, "Total Revenue", "Operating Revenue")
        operating_income = _metric(income, fiscal_period, "Operating Income")
        net_income = _metric(income, fiscal_period, "Net Income")
        total_assets = _metric(balance, fiscal_period, "Total Assets")
        total_equity = _metric(
            balance,
            fiscal_period,
            "Stockholders Equity",
            "Total Equity Gross Minority Interest",
        )
        eps = _metric(income, fiscal_period, "Basic EPS", "Diluted EPS") or fallback_eps
        bps = (
            total_equity / shares_outstanding
            if total_equity is not None and shares_outstanding
            else fallback_bps
        )
        disclosed_at = fiscal_period + timedelta(days=45)
        rows.append(
            (
                ticker,
                fiscal_period.isoformat(),
                disclosed_at.isoformat(),
                revenue,
                operating_income,
                net_income,
                total_assets,
                total_equity,
                eps,
                bps,
            )
        )
    return rows


def _frame_or_empty(ticker_obj: yf.Ticker, attribute_name: str) -> pd.DataFrame:
    try:
        frame = getattr(ticker_obj, attribute_name)
    except Exception:
        return pd.DataFrame()
    if frame is None:
        return pd.DataFrame()
    return frame


def _safe_info(ticker_obj: yf.Ticker) -> dict[str, Any]:
    try:
        info = ticker_obj.get_info()
    except Exception:
        try:
            info = ticker_obj.info
        except Exception:
            return {}
    return info if isinstance(info, dict) else {}


def _metric(frame: pd.DataFrame, fiscal_period: date, *names: str) -> float | None:
    if frame.empty:
        return None
    matching_columns = [
        column
        for column in frame.columns
        if _date_from_column(column) == fiscal_period
    ]
    if not matching_columns:
        return None
    column = matching_columns[0]
    for name in names:
        if name in frame.index:
            return _float_or_none(frame.loc[name, column])
    return None


def _date_from_column(value: object) -> date | None:
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _load_tickers_file(path: Path) -> list[str]:
    resolved = path if path.is_absolute() else PROJECT_ROOT / path
    text = resolved.read_text(encoding="utf-8-sig")
    tickers = []
    for raw in text.replace(",", "\n").splitlines():
        ticker = _normalize_ticker(raw)
        if ticker and not ticker.startswith("#"):
            tickers.append(ticker)
    return sorted(dict.fromkeys(tickers))


def _normalize_ticker(value: object) -> str:
    text = str(value).strip().upper()
    if not text or text.lower() == "nan":
        return ""
    return text.replace(".", "-")


def _optional_text(value: object) -> str | None:
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    number = _float_or_none(value)
    if number is None:
        return 0
    return int(number)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download NASDAQ daily prices and basic financials into research.db."
    )
    parser.add_argument("--universe", choices=["NASDAQ100"], default="NASDAQ100")
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--since", type=_parse_date, default=None)
    parser.add_argument("--until", type=_parse_date, default=None)
    parser.add_argument("--max-tickers", type=int, default=0)
    parser.add_argument("--tickers-file", type=Path, default=None)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--sleep", type=float, default=0.25)
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--skip-financials", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
