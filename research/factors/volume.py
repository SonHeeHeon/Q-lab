"""Liquidity and trading-activity factor calculations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date as Date
from pathlib import Path

import pandas as pd

from research.factors.common import normalize_codes, split_korean_and_global, table_exists
from shared.db.session import research_db_path


def calculate_trading_days_30d(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """Count non-zero-volume trading rows in the latest 30 rows by stock."""

    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.Series(dtype="float64")

    path = db_path or research_db_path
    rows = _latest_volume_rows(
        normalized_codes,
        as_of=as_of,
        db_path=path,
        limit=30,
    )
    if rows.empty:
        return pd.Series(dtype="float64")

    values = rows.assign(active=rows["volume"].astype(float) > 0)
    return values.groupby("stock_code")["active"].sum().astype(float)


def _latest_volume_rows(
    codes: list[str],
    *,
    as_of: Date,
    db_path: Path,
    limit: int,
) -> pd.DataFrame:
    korean_codes, global_codes = split_korean_and_global(codes)
    frames: list[pd.DataFrame] = []
    with sqlite3.connect(db_path) as conn:
        if korean_codes and table_exists(conn, "prices_daily"):
            frames.append(
                _latest_volume_rows_from_table(
                    conn,
                    "prices_daily",
                    "stock_code",
                    korean_codes,
                    as_of,
                    limit=limit,
                )
            )
        if global_codes and table_exists(conn, "prices_daily_us"):
            frames.append(
                _latest_volume_rows_from_table(
                    conn,
                    "prices_daily_us",
                    "ticker",
                    global_codes,
                    as_of,
                    limit=limit,
                )
            )
    if not frames:
        return pd.DataFrame(columns=["stock_code", "volume", "rn"])
    return pd.concat(frames, ignore_index=True)


def _latest_volume_rows_from_table(
    conn: sqlite3.Connection,
    table_name: str,
    code_column: str,
    codes: list[str],
    as_of: Date,
    *,
    limit: int,
) -> pd.DataFrame:
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT stock_code, volume, rn
        FROM (
            SELECT
                {code_column} AS stock_code,
                volume,
                ROW_NUMBER() OVER (
                    PARTITION BY {code_column}
                    ORDER BY date DESC
                ) AS rn
            FROM {table_name}
            WHERE {code_column} IN ({placeholders})
              AND date <= ?
        )
        WHERE rn <= ?
    """
    return pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat(), limit])


def calculate_volume_spike(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """Today volume divided by the previous 20-row average volume."""

    normalized_codes = normalize_codes(codes)
    if not normalized_codes:
        return pd.Series(dtype="float64")

    path = db_path or research_db_path
    rows = _latest_volume_rows(
        normalized_codes,
        as_of=as_of,
        db_path=path,
        limit=21,
    )
    if rows.empty:
        return pd.Series(dtype="float64")

    values: dict[str, float] = {}
    for code, group in rows.groupby("stock_code"):
        ordered = group.sort_values("rn").reset_index(drop=True)
        if len(ordered) < 21:
            continue
        today_volume = float(ordered.loc[0, "volume"])
        trailing_avg = float(ordered.loc[1:, "volume"].astype(float).mean())
        if trailing_avg > 0:
            values[code] = today_volume / trailing_avg
    return pd.Series(values, dtype="float64")
