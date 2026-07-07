"""data_sync incremental-ingestion tests (previously a docstring stub).

Verifies incremental start-date computation from a fixture research DB and
that the job wires each loader with the right window — loaders are patched,
no network.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest

import backend.app.services.batch.data_sync as ds

TODAY = date(2026, 7, 7)


@dataclass
class _FakeResult:
    requested: int


def _make_research_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE prices_daily (stock_code TEXT, date TEXT)")
        conn.executemany(
            "INSERT INTO prices_daily VALUES (?,?)",
            [
                ("000001", "2016-01-04"),
                ("000001", "2026-07-04"),
                ("000002", "2026-07-04"),
            ],
        )
        conn.execute("CREATE TABLE market_caps (stock_code TEXT, date TEXT)")
        conn.execute("INSERT INTO market_caps VALUES ('000001', '2026-06-30')")
        # investor_flows_daily deliberately ABSENT → fallback to price start.
        conn.execute("CREATE TABLE market_index (index_code TEXT, date TEXT)")
        conn.execute("INSERT INTO market_index VALUES ('KOSPI', '2026-07-03')")


def test_incremental_start_resumes_with_overlap(tmp_path: Path) -> None:
    db = tmp_path / "research.db"
    _make_research_db(db)
    with sqlite3.connect(db) as conn:
        start = ds._incremental_start(conn, "market_caps", TODAY, 5)
        assert start == date(2026, 6, 25)  # max(2026-06-30) − 5d
        missing = ds._incremental_start(
            conn, "investor_flows_daily", TODAY, 5, fallback=date(2016, 1, 4)
        )
        assert missing == date(2016, 1, 4)  # absent table → fallback backfill
        bare = ds._incremental_start(conn, "no_such_table", TODAY, 5)
        assert bare == TODAY - timedelta(days=5)


async def test_run_data_sync_wires_loaders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "research.db"
    _make_research_db(db)
    monkeypatch.setattr(ds, "research_db_path", db)

    calls: dict[str, dict] = {}

    async def fake_prices(codes, *, start, end):
        calls["prices"] = {"codes": list(codes), "start": start, "end": end}
        return _FakeResult(10)

    async def fake_caps(codes, *, start, end):
        calls["caps"] = {"start": start, "end": end}
        return _FakeResult(20)

    async def fake_flows(codes, *, start, end):
        calls["flows"] = {"start": start, "end": end}
        return _FakeResult(30)

    async def fake_indices(*, start, end):
        calls["indices"] = {"start": start, "end": end}
        return [_FakeResult(4), _FakeResult(5)]

    async def fake_us(*, start, end):
        calls["us"] = {"start": start, "end": end}
        return _FakeResult(7)

    class _FakeMacro:
        total = 6

    async def fake_macro(*, start, end):
        calls["macro"] = {"start": start, "end": end}
        return _FakeMacro()

    monkeypatch.setattr(ds, "update_prices", fake_prices)
    monkeypatch.setattr(ds, "update_market_caps", fake_caps)
    monkeypatch.setattr(ds, "update_investor_flows", fake_flows)
    monkeypatch.setattr(ds, "update_market_indices", fake_indices)
    monkeypatch.setattr(ds, "update_us_prices_incremental", fake_us)
    monkeypatch.setattr(ds, "update_macro", fake_macro)

    summary = await ds.run_data_sync(end=TODAY)

    assert calls["prices"]["codes"] == ["000001", "000002"]
    assert calls["prices"]["start"] == date(2026, 6, 29)   # 7/4 − 5d
    assert calls["caps"]["start"] == date(2026, 6, 25)     # 6/30 − 5d
    assert calls["flows"]["start"] == date(2026, 6, 29)    # absent → price start
    assert calls["indices"]["start"] == date(2026, 6, 28)  # 7/3 − 5d
    assert calls["us"]["start"] == date(2026, 6, 29)       # absent → price start
    assert all(c["end"] == TODAY for c in calls.values())
    assert summary.to_dict() == {
        "prices": 10,
        "market_caps": 20,
        "investor_flows": 30,
        "market_indices": 9,
        "us_prices": 7,
        "macro": 6,
        "errors": 0,
    }


async def test_run_data_sync_counts_step_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "research.db"
    _make_research_db(db)
    monkeypatch.setattr(ds, "research_db_path", db)

    async def ok(codes=None, *, start, end):
        return _FakeResult(1)

    async def boom(codes=None, *, start, end):
        raise RuntimeError("krx down")

    async def ok_indices(*, start, end):
        return [_FakeResult(1)]

    async def ok_us(*, start, end):
        return _FakeResult(1)

    class _FakeMacro:
        total = 1

    async def ok_macro(*, start, end):
        return _FakeMacro()

    monkeypatch.setattr(ds, "update_prices", ok)
    monkeypatch.setattr(ds, "update_market_caps", boom)
    monkeypatch.setattr(ds, "update_investor_flows", ok)
    monkeypatch.setattr(ds, "update_market_indices", ok_indices)
    monkeypatch.setattr(ds, "update_us_prices_incremental", ok_us)
    monkeypatch.setattr(ds, "update_macro", ok_macro)

    summary = await ds.run_data_sync(end=TODAY)
    assert summary.errors == 1
    assert summary.prices == 1 and summary.investor_flows == 1  # other steps ran
    assert summary.us_prices == 1 and summary.macro == 1
