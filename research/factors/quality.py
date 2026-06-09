"""Point-in-time quality factor calculations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date as Date
from pathlib import Path

import pandas as pd

from research.factors.common import normalize_codes, split_korean_and_global, table_exists
from shared.db.session import research_db_path


def calculate_roe(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """ROE = latest disclosed net_income / total_equity."""

    frame = calculate_quality_factors(codes, as_of=as_of, db_path=db_path)
    return frame["ROE"] if "ROE" in frame else pd.Series(dtype="float64")


def calculate_roa(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """ROA = latest disclosed net_income / total_assets."""

    frame = calculate_quality_factors(codes, as_of=as_of, db_path=db_path)
    return frame["ROA"] if "ROA" in frame else pd.Series(dtype="float64")


def calculate_quality_factors(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Return quality factors using financials disclosed by ``as_of`` only."""

    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.DataFrame(columns=["ROE", "ROA"])

    path = db_path or research_db_path
    with sqlite3.connect(path) as conn:
        financials = _ttm_financials(conn, normalized_codes, as_of)

    frame = pd.DataFrame(index=normalized_codes)
    frame.index.name = "code"
    frame = frame.join(financials)
    frame["ROE"] = _safe_divide(frame["net_income_ttm"], frame["total_equity"])
    frame["ROA"] = _safe_divide(frame["net_income_ttm"], frame["total_assets"])
    frame.loc[frame["total_equity"] <= 0, "ROE"] = pd.NA
    frame.loc[frame["total_assets"] <= 0, "ROA"] = pd.NA
    return frame[["ROE", "ROA"]]


def _ttm_financials(
    conn: sqlite3.Connection,
    codes: list[str],
    as_of: Date,
) -> pd.DataFrame:
    korean_codes, global_codes = split_korean_and_global(codes)
    frames: list[pd.DataFrame] = []
    if korean_codes and table_exists(conn, "financials"):
        frames.append(_ttm_financials_from_table(conn, "financials", "stock_code", korean_codes, as_of))
    if global_codes and table_exists(conn, "financials_us"):
        frames.append(_ttm_financials_from_table(conn, "financials_us", "ticker", global_codes, as_of))
    if not frames:
        return pd.DataFrame(
            index=pd.Index([], name="stock_code"),
            columns=["net_income_ttm", "total_equity", "total_assets"],
        )
    return pd.concat(frames).sort_index()


def _ttm_financials_from_table(
    conn: sqlite3.Connection,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
) -> pd.DataFrame:
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT stock_code, net_income, total_equity, total_assets
        FROM (
            SELECT
                {code_column} AS stock_code,
                net_income,
                total_equity,
                total_assets,
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
    latest = pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat()])

    ttm_sql = f"""
        SELECT stock_code, net_income
        FROM (
            SELECT
                {code_column} AS stock_code,
                net_income,
                ROW_NUMBER() OVER (
                    PARTITION BY {code_column}
                    ORDER BY disclosed_at DESC, fiscal_period DESC, id DESC
                ) AS rn
            FROM {table_name}
            WHERE {code_column} IN ({placeholders})
              AND disclosed_at <= ?
              AND net_income IS NOT NULL
        )
        WHERE rn <= 4
    """
    ttm = pd.read_sql_query(ttm_sql, conn, params=[*codes, as_of.isoformat()])
    if latest.empty:
        return pd.DataFrame(
            index=pd.Index([], name="stock_code"),
            columns=["net_income_ttm", "total_equity", "total_assets"],
        )
    latest_frame = latest.set_index("stock_code")
    if ttm.empty:
        latest_frame["net_income_ttm"] = latest_frame["net_income"]
    else:
        latest_frame["net_income_ttm"] = (
            ttm.groupby("stock_code")["net_income"].sum().astype(float)
        )
        latest_frame["net_income_ttm"] = latest_frame["net_income_ttm"].fillna(
            latest_frame["net_income"]
        )
    return latest_frame[["net_income_ttm", "total_equity", "total_assets"]].astype(float)


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    safe_numerator = pd.to_numeric(numerator, errors="coerce")
    safe_denominator = pd.to_numeric(denominator, errors="coerce").replace(0, pd.NA)
    result = safe_numerator / safe_denominator
    return result.replace([float("inf"), float("-inf")], pd.NA)
