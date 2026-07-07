"""Benchmark-relative performance metrics (alpha / beta / IR / TE).

The audit flagged that market_index data existed but no benchmark-relative
metrics did — a strategy could look great absolutely while losing to simply
holding the index. These are pure functions over an equity curve and a
benchmark close series (KOSPI for KR runs, SP500 for US runs).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from math import sqrt

import pandas as pd

TRADING_DAYS_PER_YEAR = 252.0
MIN_OVERLAP_DAYS = 20


@dataclass(frozen=True, slots=True)
class BenchmarkRelative:
    beta: float
    alpha_annual: float
    information_ratio: float
    tracking_error_annual: float
    benchmark_total_return: float
    overlap_days: int


def benchmark_relative(
    equity_curve: list[tuple[Date, float]],
    benchmark_close: pd.Series,
) -> BenchmarkRelative | None:
    """CAPM-style stats of the portfolio vs a benchmark close series.

    Returns None when fewer than MIN_OVERLAP_DAYS overlapping return days
    exist (too little data for a meaningful regression).
    """
    if not equity_curve or benchmark_close is None or benchmark_close.empty:
        return None

    nav = pd.Series(
        [value for _, value in equity_curve],
        index=pd.to_datetime([day for day, _ in equity_curve]),
        dtype="float64",
    ).sort_index()
    bench = pd.to_numeric(benchmark_close, errors="coerce").dropna()
    bench.index = pd.to_datetime(bench.index)
    bench = bench.sort_index()

    joined = pd.concat({"nav": nav, "bench": bench}, axis=1, join="inner").dropna()
    if len(joined) < MIN_OVERLAP_DAYS + 1:
        return None

    rp = joined["nav"].pct_change().dropna()
    rb = joined["bench"].pct_change().dropna()
    aligned = pd.concat({"rp": rp, "rb": rb}, axis=1).dropna()
    if len(aligned) < MIN_OVERLAP_DAYS:
        return None

    var_b = float(aligned["rb"].var(ddof=1))
    if var_b <= 0:
        return None
    beta = float(aligned["rp"].cov(aligned["rb"]) / var_b)
    alpha_daily = float(aligned["rp"].mean() - beta * aligned["rb"].mean())
    active = aligned["rp"] - aligned["rb"]
    te_daily = float(active.std(ddof=1))
    tracking_error = te_daily * sqrt(TRADING_DAYS_PER_YEAR)
    information_ratio = (
        float(active.mean()) * TRADING_DAYS_PER_YEAR / tracking_error
        if tracking_error > 0
        else 0.0
    )
    bench_first = float(joined["bench"].iloc[0])
    bench_last = float(joined["bench"].iloc[-1])
    benchmark_total_return = bench_last / bench_first - 1.0 if bench_first > 0 else 0.0

    return BenchmarkRelative(
        beta=beta,
        alpha_annual=alpha_daily * TRADING_DAYS_PER_YEAR,
        information_ratio=information_ratio,
        tracking_error_annual=tracking_error,
        benchmark_total_return=benchmark_total_return,
        overlap_days=len(aligned),
    )


def load_benchmark_close(
    index_code: str,
    start: Date,
    end: Date,
    *,
    db_path=None,
) -> pd.Series:
    """Benchmark close series from market_index (KOSPI / SP500 / ...)."""
    import sqlite3

    from shared.db.session import research_db_path

    path = db_path or research_db_path
    with sqlite3.connect(path) as conn:
        has = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='market_index'"
        ).fetchone()
        if not has:
            return pd.Series(dtype="float64")
        rows = conn.execute(
            "SELECT date, close FROM market_index"
            " WHERE index_code=? AND date BETWEEN ? AND ? ORDER BY date",
            (index_code, start.isoformat(), end.isoformat()),
        ).fetchall()
    if not rows:
        return pd.Series(dtype="float64")
    return pd.Series(
        [float(close) for _, close in rows],
        index=pd.to_datetime([day for day, _ in rows]),
        dtype="float64",
    )
