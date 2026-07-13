"""Price-based momentum factor calculations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date as Date
from pathlib import Path

import pandas as pd

from research.factors.common import normalize_codes, split_korean_and_global, table_exists
from shared.db.session import research_db_path

LOOKBACK_DAYS = {
    "MOMENTUM_1M": 21,
    "MOMENTUM_3M": 63,
    "MOMENTUM_6M": 126,
    "MOMENTUM_12M": 252,
}

# 잔차(시장조정) 모멘텀 — 종목수익률에서 같은 창의 KOSPI 수익률을 뺀다.
# KR은 고전 total-return 모멘텀 유의성이 약해(Chui-Titman-Wei 2010) 시장조정 구성이
# 더 안정적이라는 문헌 대응. 베타 추정 노이즈를 피하려 베타=1(단순 시장초과)로 둔다.
IDIO_LOOKBACK_DAYS = {
    "IDIO_MOM_3M": 63,
    "IDIO_MOM_12M": 252,
}
MARKET_INDEX_CODE = "KOSPI"


def calculate_momentum(
    codes: Iterable[str],
    *,
    as_of: Date,
    lookback_days: int,
    db_path: Path | None = None,
) -> pd.Series:
    """Return point-in-time price momentum over ``lookback_days`` rows."""

    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.Series(dtype="float64")

    path = db_path or research_db_path
    korean_codes, global_codes = split_korean_and_global(normalized_codes)
    frames: list[pd.DataFrame] = []
    with sqlite3.connect(path) as conn:
        if korean_codes and table_exists(conn, "prices_daily"):
            frames.append(_price_rows(conn, "prices_daily", "stock_code", korean_codes, as_of))
        if global_codes and table_exists(conn, "prices_daily_us"):
            frames.append(_price_rows(conn, "prices_daily_us", "ticker", global_codes, as_of))

    if not frames:
        return pd.Series(dtype="float64")
    rows = pd.concat(frames, ignore_index=True)

    if rows.empty:
        return pd.Series(dtype="float64")

    values: dict[str, float] = {}
    for code, group in rows.groupby("stock_code"):
        closes = group.sort_values("date")["close"].astype(float).reset_index(drop=True)
        if len(closes) <= lookback_days:
            continue
        start = closes.iloc[-lookback_days - 1]
        end = closes.iloc[-1]
        if start > 0:
            values[code] = float(end / start - 1.0)
    return pd.Series(values, dtype="float64")


def _price_rows(
    conn: sqlite3.Connection,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
) -> pd.DataFrame:
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT {code_column} AS stock_code, date, COALESCE(adj_close, close) AS close
        FROM {table_name}
        WHERE {code_column} IN ({placeholders})
          AND date <= ?
        ORDER BY stock_code, date
    """
    return pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat()])


def calculate_named_momentum(
    factor_name: str,
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """Calculate one of MOMENTUM_1M/3M/6M/12M."""

    normalized_name = factor_name.upper()
    if normalized_name not in LOOKBACK_DAYS:
        raise ValueError(f"Unsupported momentum factor: {factor_name}")
    return calculate_momentum(
        codes,
        as_of=as_of,
        lookback_days=LOOKBACK_DAYS[normalized_name],
        db_path=db_path,
    )


def _index_return(
    conn: sqlite3.Connection,
    lookback_days: int,
    as_of: Date,
    *,
    index_code: str = MARKET_INDEX_CODE,
) -> float | None:
    """KOSPI close return over the same ``lookback_days`` rows (None if absent)."""
    if not table_exists(conn, "market_index"):
        return None
    rows = pd.read_sql_query(
        "SELECT date, close FROM market_index"
        " WHERE index_code = ? AND date <= ? ORDER BY date",
        conn,
        params=[index_code, as_of.isoformat()],
    )
    if len(rows) <= lookback_days:
        return None
    closes = rows["close"].astype(float).reset_index(drop=True)
    start = closes.iloc[-lookback_days - 1]
    end = closes.iloc[-1]
    if start <= 0:
        return None
    return float(end / start - 1.0)


def calculate_idio_momentum(
    codes: Iterable[str],
    *,
    as_of: Date,
    lookback_days: int,
    db_path: Path | None = None,
) -> pd.Series:
    """Market-adjusted momentum: stock return − KOSPI return over the same window.

    If the market series is unavailable the market leg is 0 (degrades to plain
    momentum) rather than dropping every name.
    """
    stock_mom = calculate_momentum(
        codes, as_of=as_of, lookback_days=lookback_days, db_path=db_path
    )
    if stock_mom.empty:
        return stock_mom
    path = db_path or research_db_path
    with sqlite3.connect(path) as conn:
        market = _index_return(conn, lookback_days, as_of)
    return stock_mom - (market or 0.0)


def calculate_named_idio_momentum(
    factor_name: str,
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """Calculate one of IDIO_MOM_3M/12M (market-adjusted momentum)."""

    normalized_name = factor_name.upper()
    if normalized_name not in IDIO_LOOKBACK_DAYS:
        raise ValueError(f"Unsupported idio-momentum factor: {factor_name}")
    return calculate_idio_momentum(
        codes,
        as_of=as_of,
        lookback_days=IDIO_LOOKBACK_DAYS[normalized_name],
        db_path=db_path,
    )
