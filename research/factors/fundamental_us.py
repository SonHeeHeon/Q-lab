"""US-specific fundamental factors built on SEC EDGAR data (financials_us).

These need columns only the US table carries (cfo, capex, gross_profit, buybacks,
dividends_paid, shares_out), so KR codes resolve to NA — which the grouped
composite tolerates via its coverage penalty. Factors used by AQR / Dimensional /
Robeco for US equities:

- GP_A            gross profit / assets            (Novy-Marx 2013)     higher better
- ACCRUALS        (net income − CFO) / assets      (Sloan 1996)         lower  better
- ASSET_GROWTH    Δ total assets YoY               (Cooper/CMA)         lower  better
- FCF_YIELD       (CFO − capex) / market cap       (quality-value)      higher better
- SHAREHOLDER_YIELD (buybacks + dividends)/mktcap  (US-distinctive)     higher better
- EPS_GROWTH_YOY  TTM EPS vs 1y ago                (earnings momentum)  higher better

All point-in-time: flows gate on ``disclosed_at <= as_of``; the year-ago leg gates
on ``as_of − 365d``. Market cap uses the raw (unadjusted) close × shares so it is
the actual price level on the date, not a dividend-adjusted one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date as Date
from datetime import timedelta
from pathlib import Path

import pandas as pd

from research.factors.common import normalize_codes, split_korean_and_global, table_exists
from research.factors.quality import flow_ttm_series
from shared.db.session import research_db_path

_US_TABLE = "financials_us"
_US_CODE = "ticker"


def _us_codes(codes: list[str]) -> list[str]:
    _, global_codes = split_korean_and_global(codes)
    return global_codes


def _ttm(conn: sqlite3.Connection, codes: list[str], column: str, as_of: Date) -> pd.Series:
    """Trailing-12-month sum of a flow column on financials_us (US = quarterly)."""
    return flow_ttm_series(
        conn, _US_TABLE, _US_CODE, codes, as_of, column=column, mixed_annual=False
    )


def _latest(
    conn: sqlite3.Connection, codes: list[str], column: str, as_of: Date
) -> pd.Series:
    """Latest point-in-time value of a (balance-sheet) column disclosed by as_of."""
    if column not in {r[1] for r in conn.execute(f"PRAGMA table_info({_US_TABLE})")}:
        return pd.Series(dtype="float64")
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT stock_code, val FROM (
            SELECT {_US_CODE} AS stock_code, {column} AS val,
                ROW_NUMBER() OVER (
                    PARTITION BY {_US_CODE}
                    ORDER BY disclosed_at DESC, fiscal_period DESC, id DESC
                ) AS rn
            FROM {_US_TABLE}
            WHERE {_US_CODE} IN ({placeholders})
              AND disclosed_at <= ? AND {column} IS NOT NULL
        ) WHERE rn = 1
    """
    rows = pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat()])
    if rows.empty:
        return pd.Series(dtype="float64")
    return rows.set_index("stock_code")["val"].astype(float)


def _latest_close(conn: sqlite3.Connection, codes: list[str], as_of: Date) -> pd.Series:
    """Latest raw close on/before as_of (actual price level, not dividend-adjusted)."""
    if not table_exists(conn, "prices_daily_us"):
        return pd.Series(dtype="float64")
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT ticker, close FROM (
            SELECT ticker, close,
                ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM prices_daily_us
            WHERE ticker IN ({placeholders}) AND date <= ? AND close > 0
        ) WHERE rn = 1
    """
    rows = pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat()])
    if rows.empty:
        return pd.Series(dtype="float64")
    return rows.set_index("ticker")["close"].astype(float)


def _market_cap(conn: sqlite3.Connection, codes: list[str], as_of: Date) -> pd.Series:
    price = _latest_close(conn, codes, as_of)
    shares = _latest(conn, codes, "shares_out", as_of)
    cap = (price * shares).dropna()
    return cap[cap > 0]


def _safe_ratio(numer: pd.Series, denom: pd.Series) -> pd.Series:
    aligned_n, aligned_d = numer.align(denom, join="inner")
    out = aligned_n / aligned_d
    return out.replace([float("inf"), float("-inf")], pd.NA).dropna()


def _run(codes: Iterable[str], as_of: Date, db_path: Path | None, fn) -> pd.Series:
    normalized = normalize_codes(codes)
    us = _us_codes(normalized)
    if not us:
        return pd.Series(dtype="float64")
    path = db_path or research_db_path
    with sqlite3.connect(path) as conn:
        if not table_exists(conn, _US_TABLE):
            return pd.Series(dtype="float64")
        return fn(conn, us)


def calculate_gp_a(codes, *, as_of, db_path=None) -> pd.Series:
    """Gross profitability = gross_profit(TTM) / total_assets (Novy-Marx)."""
    return _run(codes, as_of, db_path, lambda c, us: _safe_ratio(
        _ttm(c, us, "gross_profit", as_of), _latest(c, us, "total_assets", as_of)))


def calculate_accruals(codes, *, as_of, db_path=None) -> pd.Series:
    """Balance-sheet accruals = (net_income − CFO)(TTM) / total_assets (Sloan).
    Lower is better — high accruals flag low-quality earnings."""
    def _fn(conn, us):
        ni = _ttm(conn, us, "net_income", as_of)
        cfo = _ttm(conn, us, "cfo", as_of)
        assets = _latest(conn, us, "total_assets", as_of)
        n, c = ni.align(cfo, join="inner")
        return _safe_ratio(n - c, assets)
    return _run(codes, as_of, db_path, _fn)


def calculate_asset_growth(codes, *, as_of, db_path=None) -> pd.Series:
    """YoY total-asset growth (Cooper-Gulen-Schill). Lower is better."""
    year_ago = as_of - timedelta(days=365)
    def _fn(conn, us):
        now = _latest(conn, us, "total_assets", as_of)
        prior = _latest(conn, us, "total_assets", year_ago)
        n, p = now.align(prior, join="inner")
        p = p[p > 0]
        return _safe_ratio(n - p, p)  # (now-prior)/prior
    return _run(codes, as_of, db_path, _fn)


def calculate_fcf_yield(codes, *, as_of, db_path=None) -> pd.Series:
    """Free-cash-flow yield = (CFO − capex)(TTM) / market cap. Higher is better."""
    def _fn(conn, us):
        cfo = _ttm(conn, us, "cfo", as_of)
        capex = _ttm(conn, us, "capex", as_of)
        c, x = cfo.align(capex, join="inner")
        fcf = c - x  # capex stored as a positive outflow (PaymentsToAcquire…)
        return _safe_ratio(fcf, _market_cap(conn, us, as_of))
    return _run(codes, as_of, db_path, _fn)


def calculate_shareholder_yield(codes, *, as_of, db_path=None) -> pd.Series:
    """(buybacks + dividends)(TTM) / market cap — US-distinctive payout factor."""
    def _fn(conn, us):
        bb = _ttm(conn, us, "buybacks", as_of)
        dv = _ttm(conn, us, "dividends_paid", as_of)
        payout = bb.add(dv, fill_value=0.0)  # either alone still counts
        return _safe_ratio(payout, _market_cap(conn, us, as_of))
    return _run(codes, as_of, db_path, _fn)


def calculate_eps_growth_yoy(codes, *, as_of, db_path=None) -> pd.Series:
    """TTM EPS growth vs one year ago (earnings momentum / PEAD). Higher is better."""
    year_ago = as_of - timedelta(days=365)
    def _fn(conn, us):
        now = _ttm(conn, us, "eps", as_of)
        prior = _ttm(conn, us, "eps", year_ago)
        n, p = now.align(prior, join="inner")
        # normalize by |prior| so sign of growth is meaningful; drop near-zero base
        denom = p.abs()
        out = (n - p) / denom
        out = out[denom > 0.01]
        return out.replace([float("inf"), float("-inf")], pd.NA).dropna()
    return _run(codes, as_of, db_path, _fn)


_FUNDAMENTAL_US_FACTORS = {
    "GP_A": calculate_gp_a,
    "ACCRUALS": calculate_accruals,
    "ASSET_GROWTH": calculate_asset_growth,
    "FCF_YIELD": calculate_fcf_yield,
    "SHAREHOLDER_YIELD": calculate_shareholder_yield,
    "EPS_GROWTH_YOY": calculate_eps_growth_yoy,
}
