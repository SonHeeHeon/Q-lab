"""Skip-month momentum (12-1류) — 최근 skip일이 실제로 제외되는지."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from research.factors.momentum import calculate_momentum


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    """400일 동안 100 → 이후 마지막 21일만 매일 +10% 급등하는 미국 티커."""
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE prices_daily_us (ticker TEXT, date TEXT, close REAL, adj_close REAL)"
        )
        base = date(2025, 1, 1)
        price = 100.0
        for i in range(400):
            day = base + timedelta(days=i)
            if i >= 379:  # 마지막 21일 급등
                price *= 1.10
            conn.execute(
                "INSERT INTO prices_daily_us VALUES ('TEST', ?, ?, ?)",
                (day.isoformat(), price, price),
            )
    return path


def test_skip_days_excludes_recent_window(db: Path) -> None:
    as_of = date(2025, 1, 1) + timedelta(days=399)
    plain = calculate_momentum(["TEST"], as_of=as_of, lookback_days=252, db_path=db)
    skipped = calculate_momentum(
        ["TEST"], as_of=as_of, lookback_days=252, skip_days=21, db_path=db
    )
    # plain은 급등을 포함해 큰 양수, 12-1(skip=21)은 급등 전 구간만이라 ~0.
    assert plain["TEST"] > 1.0
    assert abs(skipped["TEST"]) < 0.01
