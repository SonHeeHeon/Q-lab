"""Stock-name lookup helpers backed by research.db."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from shared.db.session import research_db_path


def lookup_stock_names(codes: Iterable[str]) -> dict[str, str]:
    normalized_codes = sorted({str(code).strip().zfill(6) for code in codes if str(code).strip()})
    if not normalized_codes:
        return {}

    placeholders = ",".join("?" for _ in normalized_codes)
    sql = f"SELECT code, name FROM stocks WHERE code IN ({placeholders})"
    try:
        with sqlite3.connect(research_db_path) as conn:
            rows = conn.execute(sql, normalized_codes).fetchall()
    except sqlite3.Error:
        return {}
    return {str(code).zfill(6): str(name) for code, name in rows if name}
