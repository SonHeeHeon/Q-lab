"""Point-in-time value factor calculations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date as Date
from pathlib import Path

import pandas as pd

from research.factors.common import normalize_codes, split_korean_and_global, table_exists
from research.factors.quality import net_income_ttm_series
from shared.db.session import research_db_path


def calculate_per(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """PER = latest point-in-time price / EPS."""

    frame = calculate_value_factors(codes, as_of=as_of, db_path=db_path)
    return frame["PER"] if "PER" in frame else pd.Series(dtype="float64")


def calculate_pbr(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """PBR = latest point-in-time price / BPS."""

    frame = calculate_value_factors(codes, as_of=as_of, db_path=db_path)
    return frame["PBR"] if "PBR" in frame else pd.Series(dtype="float64")


def calculate_value_factors(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Return PER/PBR using only financials disclosed on or before ``as_of``."""

    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.DataFrame(columns=["PER", "PBR"])

    path = db_path or research_db_path
    with sqlite3.connect(path) as conn:
        prices = _latest_prices(conn, normalized_codes, as_of)
        financials = _latest_financials(conn, normalized_codes, as_of)
        ttm = _net_income_ttm(conn, normalized_codes, as_of)

    frame = pd.DataFrame(index=normalized_codes)
    frame.index.name = "code"
    frame["price"] = prices
    frame = frame.join(financials)
    frame["net_income_ttm"] = ttm.reindex(frame.index)

    shares = _share_estimate(frame)
    frame["bps"] = _fill_bps_from_equity(frame, shares)
    # PER on a consistent 12-month basis: the latest disclosure's EPS is a
    # 3-month figure whenever the newest report is an interim, which made the
    # PER cross-section mix 3-month and 12-month earnings bases (~4x apart).
    eps_ttm = _safe_divide(frame["net_income_ttm"], shares)
    eps_basis = eps_ttm.where(eps_ttm.notna(), pd.to_numeric(frame["eps"], errors="coerce"))
    frame["PER"] = _safe_divide(frame["price"], eps_basis)
    frame["PBR"] = _safe_divide(frame["price"], frame["bps"])
    frame.loc[(eps_basis <= 0).fillna(False), "PER"] = pd.NA
    frame.loc[(frame["bps"] <= 0).fillna(False), "PBR"] = pd.NA
    return frame[["PER", "PBR"]]


def _net_income_ttm(
    conn: sqlite3.Connection,
    codes: list[str],
    as_of: Date,
) -> pd.Series:
    korean_codes, global_codes = split_korean_and_global(codes)
    parts: list[pd.Series] = []
    if korean_codes and table_exists(conn, "financials"):
        parts.append(
            net_income_ttm_series(
                conn, "financials", "stock_code", korean_codes, as_of,
                mixed_annual=True,
            )
        )
    if global_codes and table_exists(conn, "financials_us"):
        parts.append(
            net_income_ttm_series(
                conn, "financials_us", "ticker", global_codes, as_of,
                mixed_annual=False,
            )
        )
    if not parts:
        return pd.Series(dtype="float64")
    return pd.concat(parts).sort_index()


def _share_estimate(frame: pd.DataFrame) -> pd.Series:
    """Share count ≈ net_income / eps from the same point-in-time disclosure.

    Both figures come from one report, so the ratio is the (weighted-average)
    share count without look-ahead — the basis for both the BPS derivation and
    the TTM-EPS scaling. Invalid (sign-mismatched or non-positive) estimates
    become NA.
    """
    eps = pd.to_numeric(frame.get("eps"), errors="coerce")
    net_income = pd.to_numeric(frame.get("net_income"), errors="coerce")
    shares = _safe_divide(net_income, eps)
    return shares.where((shares > 0).fillna(False))


def _fill_bps_from_equity(frame: pd.DataFrame, shares: pd.Series) -> pd.Series:
    """Fill missing BPS as total_equity / shares.

    DART statements carry no BPS line item, so KR ``financials.bps`` is NULL and
    PBR would silently drop out of every composite score. Applied only where
    BPS is missing and the estimate is well-defined (valid share count,
    positive equity).
    """
    bps = pd.to_numeric(frame.get("bps"), errors="coerce")
    equity = pd.to_numeric(frame.get("total_equity"), errors="coerce")
    estimate = _safe_divide(equity, shares)
    valid = shares.notna() & equity.notna() & (equity > 0)
    return bps.where(bps.notna(), estimate.where(valid))


def _latest_prices(
    conn: sqlite3.Connection,
    codes: list[str],
    as_of: Date,
) -> pd.Series:
    korean_codes, global_codes = split_korean_and_global(codes)
    series: list[pd.Series] = []
    if korean_codes and table_exists(conn, "prices_daily"):
        series.append(_latest_prices_from_table(conn, "prices_daily", "stock_code", korean_codes, as_of))
    if global_codes and table_exists(conn, "prices_daily_us"):
        series.append(_latest_prices_from_table(conn, "prices_daily_us", "ticker", global_codes, as_of))
    if not series:
        return pd.Series(dtype="float64")
    return pd.concat(series).sort_index()


def _latest_prices_from_table(
    conn: sqlite3.Connection,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
) -> pd.Series:
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT stock_code, close
        FROM (
            SELECT
                {code_column} AS stock_code,
                COALESCE(adj_close, close) AS close,
                ROW_NUMBER() OVER (
                    PARTITION BY {code_column}
                    ORDER BY date DESC
                ) AS rn
            FROM {table_name}
            WHERE {code_column} IN ({placeholders})
              AND date <= ?
        )
        WHERE rn = 1
    """
    rows = pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat()])
    if rows.empty:
        return pd.Series(dtype="float64")
    return rows.set_index("stock_code")["close"].astype(float)


def _latest_financials(
    conn: sqlite3.Connection,
    codes: list[str],
    as_of: Date,
) -> pd.DataFrame:
    korean_codes, global_codes = split_korean_and_global(codes)
    frames: list[pd.DataFrame] = []
    if korean_codes and table_exists(conn, "financials"):
        frames.append(
            _latest_financials_from_table(conn, "financials", "stock_code", korean_codes, as_of)
        )
    if global_codes and table_exists(conn, "financials_us"):
        frames.append(
            _latest_financials_from_table(conn, "financials_us", "ticker", global_codes, as_of)
        )
    if not frames:
        return pd.DataFrame(
            index=pd.Index([], name="stock_code"),
            columns=_FINANCIAL_COLUMNS,
        )
    return pd.concat(frames).sort_index()


_FINANCIAL_COLUMNS = ["eps", "bps", "total_equity", "net_income"]


def _latest_financials_from_table(
    conn: sqlite3.Connection,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
) -> pd.DataFrame:
    placeholders = ",".join("?" for _ in codes)
    # The US table is created ad-hoc by the download script, so guard against
    # missing columns by selecting NULL for any the table does not have.
    available = _table_columns(conn, table_name)
    selects = ",\n                ".join(
        column if column in available else f"NULL AS {column}"
        for column in _FINANCIAL_COLUMNS
    )
    sql = f"""
        SELECT stock_code, {", ".join(_FINANCIAL_COLUMNS)}
        FROM (
            SELECT
                {code_column} AS stock_code,
                {selects},
                ROW_NUMBER() OVER (
                    PARTITION BY {code_column}
                    ORDER BY disclosed_at DESC, fiscal_period DESC, id DESC
                ) AS rn
            FROM {table_name}
            WHERE {code_column} IN ({placeholders})
              AND disclosed_at <= ?
        )
        WHERE rn = 1
    """
    rows = pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat()])
    if rows.empty:
        return pd.DataFrame(
            index=pd.Index([], name="stock_code"),
            columns=_FINANCIAL_COLUMNS,
        )
    frame = rows.set_index("stock_code")
    return frame[_FINANCIAL_COLUMNS].astype(float)


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    safe_numerator = pd.to_numeric(numerator, errors="coerce")
    safe_denominator = pd.to_numeric(denominator, errors="coerce").replace(0, pd.NA)
    result = safe_numerator / safe_denominator
    return result.replace([float("inf"), float("-inf")], pd.NA)
