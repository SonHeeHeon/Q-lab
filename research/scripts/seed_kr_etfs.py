"""Seed the curated KR ETF universe into ``stocks`` + ``prices_daily``.

Reads ``data/manual/kr_etf_universe.csv`` (code,name,category,tax_class;
``#``-prefixed lines are comments) and, for each ETF, upserts a ``stocks``
row (market='ETF') and backfills daily OHLCV prices — mirroring how
``research/data_ingestion/etf_loader.py::update_kr_etf_prices`` stores KR
ETFs (stocks row must exist before prices_daily due to the FK).

Price fetching defaults to the same pykrx "Naver" OHLCV path used by
``research/data_ingestion/pykrx_loader.py::update_prices``
(``stock.get_market_ohlcv_by_date(..., "d", True)``), with a
FinanceDataReader fallback on failure — NOT the dedicated
``get_etf_ohlcv_by_date`` endpoint, which this loader does not use.

A code whose price fetch raises or returns empty data is skipped entirely
(no ``stocks`` row is written for it either) so a single bad/delisted code
can't pollute the universe with metadata that has no backing prices.

ENVIRONMENT CAVEAT: in this dev sandbox the network is mocked, so
``get_market_ohlcv_by_date`` returns SYNTHETIC OHLCV for any 6-digit code
(not real market data) up to the sandbox's faked "today". In your real
environment this same script fetches real KRX/Naver data.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.data_ingestion.pykrx_loader import (
    _fdr_price_frame,
    _price_rows_from_frame,
    _pykrx_stock,
    _to_yyyymmdd,
)
from shared.db.session import research_db_path

DEFAULT_CURATED_CSV = PROJECT_ROOT / "data" / "manual" / "kr_etf_universe.csv"

PriceFn = Callable[[str, date, date], "pd.DataFrame | None"]


def read_curated_universe(path: Path | str = DEFAULT_CURATED_CSV) -> list[dict[str, str]]:
    """Parse the curated KR ETF CSV, skipping ``#`` comments and blank lines."""

    resolved = Path(path)
    data_lines: list[str] = []
    with resolved.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            data_lines.append(line)

    reader = csv.DictReader(data_lines)
    rows: list[dict[str, str]] = []
    for row in reader:
        code = (row.get("code") or "").strip()
        if not code:
            continue
        rows.append(
            {
                "code": code,
                "name": (row.get("name") or "").strip(),
                "category": (row.get("category") or "").strip(),
                "tax_class": (row.get("tax_class") or "").strip(),
            }
        )
    return rows


def _default_price_fn(code: str, start: date, end: date) -> pd.DataFrame:
    """Default fetch: pykrx's Naver-backed OHLCV path, FDR fallback on error.

    Mirrors ``pykrx_loader.update_prices`` — NOT the ETF-dedicated
    ``get_etf_ohlcv_by_date`` endpoint (see module docstring).
    """

    stock = _pykrx_stock()
    try:
        return stock.get_market_ohlcv_by_date(
            _to_yyyymmdd(start), _to_yyyymmdd(end), code, "d", True
        )
    except Exception as exc:
        print(f"[seed_kr_etfs:warn] pykrx price failed for {code}: {exc}")
        return _fdr_price_frame(code, start, end)


def seed_kr_etfs(
    codes: Iterable[str] | None = None,
    *,
    start: date,
    end: date,
    db_path: Path | str | None = None,
    price_fn: PriceFn | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Seed curated KR ETFs into ``stocks`` + ``prices_daily``.

    Fail-safe: a code whose ``price_fn`` raises or returns empty data is
    recorded in ``result["skipped"]`` and gets NO ``stocks`` row either
    (skipped entirely), so a bad/delisted code can't pollute the universe
    with metadata that has no backing prices.
    """

    universe = read_curated_universe()
    if codes is not None:
        wanted = {str(code).strip().zfill(6) for code in codes}
        universe = [row for row in universe if row["code"] in wanted]

    result: dict[str, Any] = {"seeded": [], "skipped": [], "price_rows": 0}

    if dry_run:
        result["seeded"] = [row["code"] for row in universe]
        return result

    resolved_db_path = Path(db_path) if db_path is not None else research_db_path
    fetch = price_fn or _default_price_fn

    with sqlite3.connect(resolved_db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        for row in universe:
            code = row["code"]
            try:
                df = fetch(code, start, end)
            except Exception as exc:
                print(f"[seed_kr_etfs:warn] price fetch raised for {code}: {exc}")
                result["skipped"].append(code)
                continue

            price_rows = _price_rows_from_frame(code, df)
            if not price_rows:
                print(
                    f"[seed_kr_etfs:warn] no price rows for {code}; skipping "
                    "(no stocks row written either)"
                )
                result["skipped"].append(code)
                continue

            listed_at = price_rows[0]["date"]
            conn.execute(
                "INSERT INTO stocks"
                " (code, name, market, sector, industry, listed_at, delisted_at, is_delisted)"
                " VALUES (?,?,?,?,?,?,?,0)"
                " ON CONFLICT(code) DO UPDATE SET name=excluded.name, market=excluded.market",
                (code, row["name"] or code, "ETF", None, None, listed_at.isoformat(), None),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO prices_daily"
                " (stock_code, date, open, high, low, close, volume, adj_close)"
                " VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        price_row["stock_code"],
                        price_row["date"].isoformat(),
                        str(price_row["open"]),
                        str(price_row["high"]),
                        str(price_row["low"]),
                        str(price_row["close"]),
                        price_row["volume"],
                        str(price_row["adj_close"]) if price_row["adj_close"] is not None else None,
                    )
                    for price_row in price_rows
                ],
            )
            result["seeded"].append(code)
            result["price_rows"] += len(price_rows)
        conn.commit()

    return result


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed the curated KR ETF universe (stocks + prices_daily)."
    )
    parser.add_argument("--start", type=_parse_date, required=True)
    parser.add_argument("--end", type=_parse_date, default=None, help="default: today")
    parser.add_argument(
        "--codes", nargs="*", default=None, help="Optional subset of ETF codes"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", type=Path, default=None, help="default: research_db_path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    end = args.end or date.today()
    result = seed_kr_etfs(
        codes=args.codes,
        start=args.start,
        end=end,
        db_path=args.db,
        dry_run=args.dry_run,
    )
    print(
        f"[seed_kr_etfs] seeded={len(result['seeded'])} "
        f"skipped={len(result['skipped'])} price_rows={result['price_rows']}"
    )
    if result["skipped"]:
        print(f"[seed_kr_etfs] skipped codes: {result['skipped']}")


if __name__ == "__main__":
    main()
