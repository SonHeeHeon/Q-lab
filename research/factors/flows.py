"""Point-in-time investor-flow (수급) factor calculations.

Flow strength = trailing N-day net purchase value ÷ current market cap, so a
1,000억 net foreign buy means something very different for a 5,000억 small cap
than for 삼성전자. Requires both investor_flows_daily and market_caps data;
codes missing either stay NA (never silently unnormalized).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date as Date
from pathlib import Path

import pandas as pd

from research.factors.common import normalize_codes, table_exists
from shared.db.session import research_db_path

FLOW_WINDOW_DAYS = 20


def calculate_foreign_net_20d(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """20-day cumulative foreign net purchase ÷ market cap."""

    return _flow_strength(codes, as_of=as_of, db_path=db_path, column="foreign_net")


def calculate_inst_net_20d(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None = None,
) -> pd.Series:
    """20-day cumulative institutional net purchase ÷ market cap."""

    return _flow_strength(codes, as_of=as_of, db_path=db_path, column="inst_net")


def _flow_strength(
    codes: Iterable[str],
    *,
    as_of: Date,
    db_path: Path | None,
    column: str,
    window: int = FLOW_WINDOW_DAYS,
) -> pd.Series:
    normalized_codes = normalize_codes(codes)
    korean_codes = [code for code in normalized_codes if code.isdigit()]
    if not korean_codes:
        return pd.Series(dtype="float64")

    path = db_path or research_db_path
    with sqlite3.connect(path) as conn:
        if not table_exists(conn, "investor_flows_daily") or not table_exists(
            conn, "market_caps"
        ):
            return pd.Series(dtype="float64")
        flows = _window_flow_sum(conn, korean_codes, as_of, column, window)
        caps = _latest_market_caps(conn, korean_codes, as_of)

    if flows.empty or caps.empty:
        return pd.Series(dtype="float64")
    strength = flows / caps.reindex(flows.index)
    return strength.dropna()


def _window_flow_sum(
    conn: sqlite3.Connection,
    codes: list[str],
    as_of: Date,
    column: str,
    window: int,
) -> pd.Series:
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT stock_code, SUM({column}) AS flow_sum
        FROM (
            SELECT
                stock_code,
                {column},
                ROW_NUMBER() OVER (
                    PARTITION BY stock_code
                    ORDER BY date DESC
                ) AS rn
            FROM investor_flows_daily
            WHERE stock_code IN ({placeholders})
              AND date <= ?
              AND {column} IS NOT NULL
        )
        WHERE rn <= ?
        GROUP BY stock_code
    """
    rows = pd.read_sql_query(
        sql, conn, params=[*codes, as_of.isoformat(), window]
    )
    if rows.empty:
        return pd.Series(dtype="float64")
    return rows.set_index("stock_code")["flow_sum"].astype(float)


def _latest_market_caps(
    conn: sqlite3.Connection,
    codes: list[str],
    as_of: Date,
) -> pd.Series:
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT stock_code, market_cap
        FROM (
            SELECT
                stock_code,
                market_cap,
                ROW_NUMBER() OVER (
                    PARTITION BY stock_code
                    ORDER BY date DESC
                ) AS rn
            FROM market_caps
            WHERE stock_code IN ({placeholders})
              AND date <= ?
        )
        WHERE rn = 1
    """
    rows = pd.read_sql_query(sql, conn, params=[*codes, as_of.isoformat()])
    if rows.empty:
        return pd.Series(dtype="float64")
    caps = rows.set_index("stock_code")["market_cap"].astype(float)
    return caps.where(caps > 0)
