"""Benchmark overlay in the performance API (_benchmark_points)."""

from __future__ import annotations

from datetime import date

import pandas as pd

import backend.app.api.performance as perf_api
from backend.app.services.performance.service import ModePerformance
from research.backtest.metrics import compute_metrics


def _perf(start: date | None, end: date | None) -> ModePerformance:
    return ModePerformance(
        strategy="value_v1",
        mode="PAPER",
        source="BROKER_SNAPSHOT",
        equity_curve=[],
        metrics=compute_metrics([], []),
        total_return=0.0,
        initial_nav=None,
        current_nav=None,
        start_date=start,
        as_of=end,
    )


def test_overlay_populates_from_market_index(monkeypatch):
    series = pd.Series(
        [2500.0, 2510.0],
        index=pd.to_datetime(["2026-07-01", "2026-07-02"]),
    )
    monkeypatch.setattr(perf_api, "load_benchmark_close", lambda *a, **k: series)
    points = perf_api._benchmark_points(_perf(date(2026, 7, 1), date(2026, 7, 2)))
    assert points is not None and len(points) == 2
    assert points[0].date == date(2026, 7, 1)
    assert points[1].nav == 2510.0


def test_overlay_none_without_window_or_data(monkeypatch):
    assert perf_api._benchmark_points(_perf(None, None)) is None
    monkeypatch.setattr(
        perf_api, "load_benchmark_close", lambda *a, **k: pd.Series(dtype="float64")
    )
    assert perf_api._benchmark_points(_perf(date(2026, 7, 1), date(2026, 7, 2))) is None
