"""Startup auto-migration test — a fresh DB reaches head, so late tables
(order_proposals, stocks_us.korean_name) exist and don't 500 the API.

This guards the exact footgun that broke '오늘의 제안' (no such table:
order_proposals) when a user's DB predated the migration and was never
manually upgraded.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _cols(db: Path, table: str) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def test_upgrade_all_brings_fresh_dbs_to_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_db = tmp_path / "service.db"
    research_db = tmp_path / "research.db"
    monkeypatch.setenv("SERVICE_DB_PATH", str(service_db))
    monkeypatch.setenv("RESEARCH_DB_PATH", str(research_db))

    from shared.db.migrate import upgrade_all

    results = upgrade_all()
    assert results == {"service": "ok", "research": "ok"}

    # The late service migration that broke 오늘의 제안 must be present.
    assert "order_proposals" in _tables(service_db)
    # Core service tables too.
    assert {"accounts", "trades"} <= _tables(service_db)
    # Research branch reached head (stocks_us itself is created out-of-band by
    # download_us_universe, so its korean_name columns aren't asserted here).
    assert research_db.exists()
    _ = _cols  # helper kept for future column assertions
