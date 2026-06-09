"""Shared helpers for point-in-time factor calculators."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable


def normalize_code(code: object) -> str:
    """Normalize Korean six-digit codes and US-style tickers without mixing them."""

    text = str(code).strip().upper()
    if not text:
        return ""
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text.replace(".", "-")


def normalize_codes(codes: Iterable[object]) -> list[str]:
    return sorted({normalized for code in codes if (normalized := normalize_code(code))})


def split_korean_and_global(codes: Iterable[str]) -> tuple[list[str], list[str]]:
    korean: list[str] = []
    global_: list[str] = []
    for code in codes:
        if code.isdigit() and len(code) == 6:
            korean.append(code)
        else:
            global_.append(code)
    return korean, global_


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        [table_name],
    ).fetchone()
    return row is not None
