"""백테스트 체결 종목명 맵 — KR 이름 조회 + US 티커 폴백 + 미등록 생략."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app.api.backtest import _trade_names


@pytest.fixture()
def names_db(tmp_path: Path) -> Path:
    db = tmp_path / "research.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE stocks (code TEXT PRIMARY KEY, name TEXT,"
            " market TEXT, listed_at TEXT, delisted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO stocks (code, name) VALUES ('069500', 'KODEX 200')"
        )
        conn.execute(
            "CREATE TABLE stocks_us (ticker TEXT PRIMARY KEY, name TEXT NOT NULL,"
            " exchange TEXT NOT NULL DEFAULT 'NASDAQ')"
        )
        conn.execute(
            "INSERT INTO stocks_us (ticker, name) VALUES ('AAPL', 'Apple Inc.')"
        )
    return db


def test_trade_names_kr_and_us(names_db: Path):
    trades = [
        {"code": "069500"}, {"code": "AAPL"}, {"code": "999999"},
        {"code": "069500"},  # 중복은 1회만 조회
    ]
    names = _trade_names(trades, db_path=names_db)
    assert names["069500"] == "KODEX 200"
    assert names["AAPL"] == "Apple Inc."
    assert "999999" not in names  # 미등록 코드는 생략(프런트가 코드 폴백)


def test_trade_names_empty():
    assert _trade_names([], db_path=Path("/nonexistent.db")) == {}
