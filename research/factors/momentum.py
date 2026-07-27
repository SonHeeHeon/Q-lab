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

# 스킵월 모멘텀(Jegadeesh-Titman "12-1"): 룩백 수익률에서 최근 skip일을 제외한다
# — 최근 1개월은 단기 반전(reversal)이 지배해 포함하면 신호가 오염된다는 표준 구성.
SKIP_LOOKBACK_DAYS = {
    "MOMENTUM_12_1": (252, 21),
    "MOMENTUM_6_1": (126, 21),
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
    skip_days: int = 0,
    db_path: Path | None = None,
) -> pd.Series:
    """Return point-in-time price momentum over ``lookback_days`` rows.

    ``skip_days``>0 excludes the most recent rows (skip-month momentum, e.g.
    12-1): return is measured from t-lookback to t-skip."""

    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.Series(dtype="float64")

    path = db_path or research_db_path
    korean_codes, global_codes = split_korean_and_global(normalized_codes)
    since = _lookback_floor(as_of, lookback_days)
    frames: list[pd.DataFrame] = []
    with sqlite3.connect(path) as conn:
        if korean_codes and table_exists(conn, "prices_daily"):
            frames.append(_price_rows(conn, "prices_daily", "stock_code", korean_codes, as_of, since))
        if global_codes and table_exists(conn, "prices_daily_us"):
            frames.append(_price_rows(conn, "prices_daily_us", "ticker", global_codes, as_of, since))

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
        end = closes.iloc[-1 - skip_days] if skip_days else closes.iloc[-1]
        if start > 0 and end > 0:
            values[code] = float(end / start - 1.0)
    return pd.Series(values, dtype="float64")


def _price_rows(
    conn: sqlite3.Connection,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
    since: Date | None = None,
) -> pd.DataFrame:
    """Point-in-time closes for ``codes`` up to ``as_of``. ``since`` bounds the
    window from below — critical for perf: without it every rebalance loads the
    entire (up to 20-year) history for hundreds of tickers, turning one backtest
    into minutes. Callers pass lookback+buffer so only the needed tail is read."""
    placeholders = ",".join("?" for _ in codes)
    lower = "" if since is None else " AND date >= ?"
    params: list = [*codes, as_of.isoformat()]
    if since is not None:
        params.append(since.isoformat())
    sql = f"""
        SELECT {code_column} AS stock_code, date, COALESCE(adj_close, close) AS close
        FROM {table_name}
        WHERE {code_column} IN ({placeholders})
          AND date <= ?{lower}
        ORDER BY stock_code, date
    """
    return pd.read_sql_query(sql, conn, params=params)


def _lookback_floor(as_of: Date, lookback_days: int, *, buffer: int = 20) -> Date:
    """Calendar-day floor giving ~lookback_days trading rows (×1.7 for weekends/
    holidays) plus a buffer, so the bounded query still has enough points."""
    from datetime import timedelta

    return as_of - timedelta(days=int(lookback_days * 1.7) + buffer)


def calculate_named_momentum(
    factor_name: str,
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """Calculate one of MOMENTUM_1M/3M/6M/12M."""

    normalized_name = factor_name.upper()
    if normalized_name in SKIP_LOOKBACK_DAYS:
        lookback, skip = SKIP_LOOKBACK_DAYS[normalized_name]
        return calculate_momentum(
            codes, as_of=as_of, lookback_days=lookback, skip_days=skip,
            db_path=db_path,
        )
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

    ⚠️ CAVEAT (Phase 4.3 검증): the market return is the SAME constant for every
    stock on a given day, and the grouped composite standardizes each factor with
    a cross-sectional z-score. A constant shift is invariant under z-scoring, so
    swapping MOMENTUM_→IDIO_MOM_ in qlab_alpha_v2 leaves the ranking BYTE-IDENTICAL
    (verified: score diff ~2e-16). To get a real residual-momentum effect you need
    PER-STOCK betas (stock − βᵢ·market), which reintroduces the estimation noise
    this simple form was meant to avoid. Kept as a library factor for flat/non-
    z-scored strategies; do not expect it to change the default composite.
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
