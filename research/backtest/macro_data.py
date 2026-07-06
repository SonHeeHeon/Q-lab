"""Load stored macro series from market_index for the regime gate."""

from __future__ import annotations

import sqlite3
from datetime import date as Date
from pathlib import Path

import pandas as pd

from shared.db.session import research_db_path

# Regime-gate keyword → market_index.index_code
REGIME_CODES = {
    "kospi": "KOSPI",
    "us10y": "US10Y",
    "usdkrw": "USDKRW",
    "vix": "VIX",
}


def load_regime_series(
    as_of: Date,
    *,
    db_path: Path | None = None,
    lookback_days: int = 500,
) -> dict[str, pd.Series]:
    """Return {kospi,us10y,usdkrw,vix} close series up to ``as_of`` (or {} each
    missing). Reads only rows within ``lookback_days`` before ``as_of``."""
    path = db_path or research_db_path
    start = (pd.Timestamp(as_of) - pd.Timedelta(days=lookback_days)).date()
    out: dict[str, pd.Series] = {}
    with sqlite3.connect(path) as conn:
        has_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='market_index'"
        ).fetchone()
        if not has_table:
            return out
        for key, code in REGIME_CODES.items():
            rows = conn.execute(
                "SELECT date, close FROM market_index"
                " WHERE index_code = ? AND date <= ? AND date >= ?"
                " ORDER BY date",
                (code, as_of.isoformat(), start.isoformat()),
            ).fetchall()
            if not rows:
                continue
            series = pd.Series(
                [float(close) for _, close in rows],
                index=pd.to_datetime([day for day, _ in rows]),
                dtype="float64",
            )
            out[key] = series
    return out
