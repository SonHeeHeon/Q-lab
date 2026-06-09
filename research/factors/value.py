"""Point-in-time value factor calculations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date as Date
from pathlib import Path

import pandas as pd

from research.factors.common import normalize_codes, split_korean_and_global, table_exists
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

    frame = pd.DataFrame(index=normalized_codes)
    frame.index.name = "code"
    frame["price"] = prices
    frame = frame.join(financials)

    frame["PER"] = _safe_divide(frame["price"], frame["eps"])
    frame["PBR"] = _safe_divide(frame["price"], frame["bps"])
    frame.loc[frame["eps"] <= 0, "PER"] = pd.NA
    frame.loc[frame["bps"] <= 0, "PBR"] = pd.NA
    return frame[["PER", "PBR"]]


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
        return pd.DataFrame(index=pd.Index([], name="stock_code"), columns=["eps", "bps"])
    return pd.concat(frames).sort_index()


def _latest_financials_from_table(
    conn: sqlite3.Connection,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
) -> pd.DataFrame:
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT stock_code, eps, bps
        FROM (
            SELECT
                {code_column} AS stock_code,
                eps,
                bps,
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
        return pd.DataFrame(index=pd.Index([], name="stock_code"), columns=["eps", "bps"])
    frame = rows.set_index("stock_code")
    return frame[["eps", "bps"]].astype(float)


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    safe_numerator = pd.to_numeric(numerator, errors="coerce")
    safe_denominator = pd.to_numeric(denominator, errors="coerce").replace(0, pd.NA)
    result = safe_numerator / safe_denominator
    return result.replace([float("inf"), float("-inf")], pd.NA)
