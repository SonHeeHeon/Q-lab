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
    # trades.broker (T4): Toss trades must be taggable as broker='TOSS'
    # instead of masquerading as the KIS PAPER account.
    assert "broker" in _cols(service_db, "trades")
    # Research branch reached head (stocks_us itself is created out-of-band by
    # download_us_universe, so its korean_name columns aren't asserted here).
    assert research_db.exists()
    _ = _cols  # helper kept for future column assertions


def test_upgrade_all_creates_rating_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """매수축/매도축 평가 테이블 + 배치 이력 테이블이 head에서 생성되는지 확인."""
    service_db = tmp_path / "service.db"
    research_db = tmp_path / "research.db"
    monkeypatch.setenv("SERVICE_DB_PATH", str(service_db))
    monkeypatch.setenv("RESEARCH_DB_PATH", str(research_db))

    from shared.db.migrate import upgrade_all

    results = upgrade_all()
    assert results == {"service": "ok", "research": "ok"}

    tables = _tables(service_db)
    assert {"stock_ratings", "position_ratings", "rating_batch_runs"} <= tables

    # position_ratings의 복합 PK가 (broker, account_key, code)인지 스팟체크.
    with sqlite3.connect(service_db) as conn:
        pk_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(position_ratings)")
            if row[5] > 0  # PRAGMA table_info: pk 컬럼 (0이면 PK 아님)
        }
    assert pk_cols == {"broker", "account_key", "code"}
