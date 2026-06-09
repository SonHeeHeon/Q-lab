"""Delisted-stock loader for survivorship-bias protection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy.dialects.sqlite import insert

from shared.db.models import Stock
from shared.db.session import research_session


@dataclass(frozen=True, slots=True)
class DelistedLoadResult:
    rows_seen: int
    rows_written: int


async def update_delisted(*, listed_at_default: date) -> DelistedLoadResult:
    """Fetch delisted KRX stocks and upsert them into stocks."""

    rows = await asyncio.to_thread(_load_delisted_rows_from_fdr, listed_at_default)
    await _upsert_delisted_rows(rows)
    return DelistedLoadResult(rows_seen=len(rows), rows_written=len(rows))


def _load_delisted_rows_from_fdr(listed_at_default: date) -> list[dict[str, Any]]:
    import FinanceDataReader as fdr

    try:
        df = fdr.StockListing("KRX-DELISTING")
    except Exception as exc:
        print(f"[phase2:warn] FinanceDataReader delisted lookup failed: {exc}")
        return []
    if df is None or df.empty:
        return []

    rows = []
    for _, row in df.iterrows():
        code = _first(row, "Symbol", "Code", "종목코드")
        if not code:
            continue
        delisted_at = _date_or_none(
            _first(row, "DelistingDate", "DelistedDate", "상장폐지일", "폐지일")
        )
        listed_at = _date_or_none(_first(row, "ListingDate", "상장일"))
        rows.append(
            {
                "code": str(code).zfill(6),
                "name": _first(row, "Name", "NameEng", "종목명") or str(code).zfill(6),
                "market": _normalize_market(_first(row, "Market", "시장구분")),
                "sector": None,
                "industry": None,
                "listed_at": listed_at or listed_at_default,
                "delisted_at": delisted_at,
                "is_delisted": True,
            }
        )
    return rows


async def _upsert_delisted_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with research_session() as session:
        for chunk in _chunks(rows, _safe_insert_chunk_size(rows)):
            stmt = insert(Stock).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Stock.code],
                set_={
                    "name": stmt.excluded.name,
                    "market": stmt.excluded.market,
                    "delisted_at": stmt.excluded.delisted_at,
                    "is_delisted": True,
                },
            )
            await session.execute(stmt)
        await session.commit()


def _safe_insert_chunk_size(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 1
    column_count = max(1, len(rows[0]))
    return max(1, 900 // column_count)


def _chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _first(row: pd.Series, *names: str) -> Any:
    for name in names:
        if name in row and pd.notna(row[name]):
            value = row[name]
            if str(value).strip():
                return value
    return None


def _date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _normalize_market(value: Any) -> str:
    text = str(value or "").upper()
    if "KOSDAQ" in text or "코스닥" in text:
        return "KOSDAQ"
    return "KOSPI"
