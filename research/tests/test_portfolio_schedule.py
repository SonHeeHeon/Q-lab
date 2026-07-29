"""blend_curves_schedule — 시점별 목표비중(글라이드패스) 합성."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from research.backtest.portfolio import blend_curves_schedule


def _curve(start: date, days: int, daily_ret: float) -> pd.Series:
    idx = pd.to_datetime([start + timedelta(days=i) for i in range(days)])
    return pd.Series([(1 + daily_ret) ** i for i in range(days)], index=idx)


def test_schedule_switches_weights():
    flat = _curve(date(2026, 1, 1), 120, 0.0)
    up = _curve(date(2026, 1, 1), 120, 0.01)
    schedule = [(date(2026, 1, 1), [1.0, 0.0]), (date(2026, 3, 1), [0.0, 1.0])]
    pts = blend_curves_schedule([flat, up], schedule, base_nav=1.0)
    by_date = dict(pts)
    assert by_date[date(2026, 2, 27)] == pytest.approx(1.0)  # 1구간: flat 100%
    last = pts[-1][1]
    assert last > 1.5  # 2구간: 상승 곡선 100% 반영


def test_schedule_boundary_is_continuous():
    up = _curve(date(2026, 1, 1), 120, 0.01)
    down = _curve(date(2026, 1, 1), 120, -0.005)
    schedule = [(date(2026, 1, 1), [0.7, 0.3]), (date(2026, 3, 1), [0.3, 0.7])]
    pts = blend_curves_schedule([up, down], schedule, base_nav=1.0)
    dates = [d for d, _ in pts]
    navs = [v for _, v in pts]
    i = dates.index(date(2026, 3, 2))  # 경계 직후
    assert abs(navs[i] / navs[i - 1] - 1) < 0.05  # 점프 없음(일수익률 수준)


def test_schedule_validation():
    c = _curve(date(2026, 1, 1), 30, 0.0)
    with pytest.raises(ValueError):
        blend_curves_schedule([c], [])
    with pytest.raises(ValueError):
        blend_curves_schedule(
            [c], [(date(2026, 2, 1), [1.0]), (date(2026, 1, 1), [1.0])]
        )
    with pytest.raises(ValueError):
        blend_curves_schedule([c], [(date(2026, 1, 1), [1.0])], rebalance=None)
