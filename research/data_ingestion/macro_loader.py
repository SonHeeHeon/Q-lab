"""Macro series ingestion for the regime gate (yfinance → market_index).

Stores VIX / USD-KRW / US 10Y / S&P 500 daily closes in the existing
``market_index`` table under synthetic index codes, alongside KOSPI/KOSDAQ, so
the regime gate (research.backtest.regime) can read them point-in-time. No API
key required (Yahoo Finance).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from research.data_ingestion.pykrx_loader import LoadResult, _insert_ignore
from shared.db.models import MarketIndex

# index_code (our table) → Yahoo ticker
MACRO_TICKERS = {
    "VIX": "^VIX",
    "USDKRW": "KRW=X",
    "US10Y": "^TNX",
    "SP500": "^GSPC",
}


@dataclass(frozen=True, slots=True)
class MacroLoadResult:
    per_code: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.per_code.values())


async def update_macro(*, start: date, end: date) -> MacroLoadResult:
    """Download macro closes and insert into market_index (ON CONFLICT IGNORE)."""
    frame = await asyncio.to_thread(_download_macro_frame, start, end)
    per_code: dict[str, int] = {}
    for code, ticker in MACRO_TICKERS.items():
        if ticker not in frame.columns:
            per_code[code] = 0
            continue
        rows = _macro_rows_from_close(code, frame[ticker])
        await _insert_ignore(MarketIndex, rows)
        per_code[code] = len(rows)
    return MacroLoadResult(per_code=per_code)


def _download_macro_frame(start: date, end: date) -> pd.DataFrame:
    import warnings

    import yfinance as yf

    warnings.filterwarnings("ignore")
    data = yf.download(
        list(MACRO_TICKERS.values()),
        start=start.isoformat(),
        end=end.isoformat(),
        progress=False,
        auto_adjust=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        return data["Close"]
    # Single-ticker frame → wrap so column access is uniform.
    return data[["Close"]].rename(columns={"Close": list(MACRO_TICKERS.values())[0]})


def _macro_rows_from_close(code: str, close: pd.Series) -> list[dict[str, Any]]:
    """Rows for market_index from a close series; NaN/zero closes are skipped."""
    rows: list[dict[str, Any]] = []
    for idx, value in close.items():
        if value is None or pd.isna(value) or float(value) <= 0:
            continue
        day = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        rows.append(
            {
                "index_code": code,
                "date": day,
                "close": Decimal(str(round(float(value), 6))),
            }
        )
    return rows


def as_load_results(result: MacroLoadResult) -> list[LoadResult]:
    return [
        LoadResult(name=f"market_index:{code}", requested=count, inserted_or_ignored=count)
        for code, count in result.per_code.items()
    ]
