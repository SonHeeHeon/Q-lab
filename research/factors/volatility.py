"""Low-volatility factors — the defensive anomaly (Baker-Haugen, Frazzini-Pedersen
'betting against beta'). Low-vol / low-beta stocks have historically earned higher
risk-adjusted returns than the CAPM predicts.

Realized volatility works on any market (per-stock, no benchmark). Beta needs a
market series: SPY for US (global) codes, KOSPI for KR codes. Both are "lower is
better" — set ``higher_is_better=False`` on the group factor.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date as Date
from math import sqrt
from pathlib import Path

import pandas as pd

from research.factors.common import normalize_codes, split_korean_and_global, table_exists
from research.factors.momentum import _lookback_floor, _price_rows
from shared.db.session import research_db_path

VOL_LOOKBACK_DAYS = {
    "VOLATILITY_120D": 120,
    "VOLATILITY_252D": 252,
}
BETA_LOOKBACK_DAYS = {
    "BETA_252D": 252,
}
# Market proxy per code family (returns benchmark for beta).
US_MARKET_TICKER = "SPY"
KR_MARKET_INDEX = "KOSPI"


def _close_history(
    codes: list[str], as_of: Date, path: Path, *, window: int
) -> pd.DataFrame:
    korean_codes, global_codes = split_korean_and_global(codes)
    since = _lookback_floor(as_of, window)  # bound the load to the needed tail
    frames: list[pd.DataFrame] = []
    with sqlite3.connect(path) as conn:
        if korean_codes and table_exists(conn, "prices_daily"):
            frames.append(_price_rows(conn, "prices_daily", "stock_code", korean_codes, as_of, since))
        if global_codes and table_exists(conn, "prices_daily_us"):
            frames.append(_price_rows(conn, "prices_daily_us", "ticker", global_codes, as_of, since))
    if not frames:
        return pd.DataFrame(columns=["stock_code", "date", "close"])
    return pd.concat(frames, ignore_index=True)


def calculate_volatility(
    codes: Iterable[str],
    *,
    as_of: Date,
    window: int,
    db_path: Path | None = None,
) -> pd.Series:
    """Annualized realized volatility of daily returns over the last ``window`` rows."""
    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.Series(dtype="float64")
    rows = _close_history(normalized_codes, as_of, db_path or research_db_path, window=window)
    if rows.empty:
        return pd.Series(dtype="float64")

    values: dict[str, float] = {}
    for code, group in rows.groupby("stock_code"):
        closes = group.sort_values("date")["close"].astype(float)
        returns = closes.pct_change().dropna().tail(window)
        if len(returns) < window // 2:  # need a meaningful sample, not 3 points
            continue
        std = float(returns.std(ddof=1))
        if std == std:  # not NaN
            values[code] = std * sqrt(252.0)
    return pd.Series(values, dtype="float64")


def calculate_named_volatility(
    factor_name: str,
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    name = factor_name.upper()
    if name not in VOL_LOOKBACK_DAYS:
        raise ValueError(f"Unsupported volatility factor: {factor_name}")
    return calculate_volatility(
        codes, as_of=as_of, window=VOL_LOOKBACK_DAYS[name], db_path=db_path
    )


def _market_returns(codes: list[str], as_of: Date, window: int, path: Path) -> pd.Series:
    """Daily returns of the market proxy, indexed by date (as strings)."""
    _, global_codes = split_korean_and_global(codes)
    since = _lookback_floor(as_of, window)
    with sqlite3.connect(path) as conn:
        # US universe → SPY (stored in prices_daily_us); otherwise KOSPI index.
        if global_codes and table_exists(conn, "prices_daily_us"):
            mkt = _price_rows(conn, "prices_daily_us", "ticker", [US_MARKET_TICKER], as_of, since)
        elif table_exists(conn, "market_index"):
            mkt = pd.read_sql_query(
                "SELECT ? AS stock_code, date, close FROM market_index"
                " WHERE index_code = ? AND date <= ? AND date >= ? ORDER BY date",
                conn, params=[KR_MARKET_INDEX, KR_MARKET_INDEX, as_of.isoformat(), since.isoformat()],
            )
        else:
            return pd.Series(dtype="float64")
    if mkt.empty:
        return pd.Series(dtype="float64")
    mkt = mkt.sort_values("date")
    ret = mkt.set_index("date")["close"].astype(float).pct_change().dropna().tail(window)
    return ret


def calculate_beta(
    codes: Iterable[str],
    *,
    as_of: Date,
    window: int,
    db_path: Path | None = None,
) -> pd.Series:
    """CAPM beta vs the market proxy over the last ``window`` rows (date-aligned)."""
    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.Series(dtype="float64")
    path = db_path or research_db_path
    market = _market_returns(normalized_codes, as_of, window, path)
    if market.empty or float(market.var(ddof=1) or 0.0) == 0.0:
        return pd.Series(dtype="float64")
    mkt_var = float(market.var(ddof=1))
    rows = _close_history(normalized_codes, as_of, path, window=window)
    if rows.empty:
        return pd.Series(dtype="float64")

    values: dict[str, float] = {}
    for code, group in rows.groupby("stock_code"):
        stock_ret = (
            group.sort_values("date").set_index("date")["close"].astype(float).pct_change().dropna()
        )
        aligned = pd.concat([stock_ret, market], axis=1, join="inner").tail(window)
        if len(aligned) < window // 2:
            continue
        cov = float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]))
        values[code] = cov / mkt_var
    return pd.Series(values, dtype="float64")


def calculate_named_beta(
    factor_name: str,
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    name = factor_name.upper()
    if name not in BETA_LOOKBACK_DAYS:
        raise ValueError(f"Unsupported beta factor: {factor_name}")
    return calculate_beta(
        codes, as_of=as_of, window=BETA_LOOKBACK_DAYS[name], db_path=db_path
    )


if __name__ == "__main__":  # ponytail: runnable check, no DB needed
    import pandas as _pd

    # A calm series and a jumpy series → jumpy must score higher volatility.
    def _vol(returns):
        return float(_pd.Series(returns).std(ddof=1)) * sqrt(252.0)

    calm = [0.001, -0.001, 0.0005, -0.0005] * 30
    jumpy = [0.05, -0.05, 0.04, -0.04] * 30
    assert _vol(calm) < _vol(jumpy), "low-vol must rank below high-vol"
    # Beta of a series identical to market is ~1.0
    mkt = _pd.Series([0.01, -0.02, 0.015, -0.005, 0.02] * 60)
    beta_self = float(mkt.cov(mkt)) / float(mkt.var(ddof=1))
    assert abs(beta_self - 1.0) < 1e-9, "beta vs itself must be 1.0"
    print("volatility.py self-check OK")
