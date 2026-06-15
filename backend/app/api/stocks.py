"""Stock detail API for research-driven frontend views."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.schemas.portfolio import ApiEnvelope
from research.factors.common import normalize_code
from research.factors.quality import calculate_roa, calculate_roe
from research.factors.value import calculate_pbr, calculate_per
from shared.db.session import research_db_path, service_db_path

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


class PricePoint(BaseModel):
    date: Date
    close: float
    volume: int


class StockDetailResponse(BaseModel):
    code: str
    name: str | None
    market: str | None
    sector: str | None
    industry: str | None
    as_of: Date | None
    latest_price: PricePoint | None
    factors: dict[str, float | None]
    factor_ranks: dict[str, float | None]
    price_history: list[PricePoint]
    local_activity: dict[str, Any]


@router.get("/{code}", response_model=ApiEnvelope[StockDetailResponse])
async def get_stock_detail(
    code: str,
    as_of: Date | None = Query(default=None),
    history_days: int = Query(default=250, ge=1, le=2500),
) -> ApiEnvelope[StockDetailResponse]:
    response = await asyncio.to_thread(
        _build_stock_detail,
        normalize_code(code),
        as_of,
        history_days,
    )
    return ApiEnvelope(data=response, error=None)


def _build_stock_detail(
    code: str,
    as_of: Date | None,
    history_days: int,
) -> StockDetailResponse:
    selected_date = as_of or _latest_price_date(code)
    meta = _stock_meta(code)
    history = _price_history(code, selected_date, history_days)
    latest_price = history[-1] if history else None
    factor_values = _factor_values(code, selected_date)
    factor_ranks = _factor_ranks(code, selected_date, meta.get("market"))
    return StockDetailResponse(
        code=code,
        name=meta.get("name"),
        market=meta.get("market"),
        sector=meta.get("sector"),
        industry=meta.get("industry"),
        as_of=selected_date,
        latest_price=latest_price,
        factors=factor_values,
        factor_ranks=factor_ranks,
        price_history=history,
        local_activity=_local_activity(code),
    )


def _stock_meta(code: str) -> dict[str, str | None]:
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute(
            """
            SELECT name, market, sector, industry
            FROM stocks
            WHERE code = ?
            """,
            [code],
        ).fetchone()
    if row is None:
        return {"name": None, "market": None, "sector": None, "industry": None}
    name, market, sector, industry = row
    return {
        "name": name,
        "market": market,
        "sector": sector,
        "industry": industry,
    }


def _latest_price_date(code: str) -> Date | None:
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM prices_daily WHERE stock_code = ?",
            [code],
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return Date.fromisoformat(str(row[0]))


def _price_history(
    code: str,
    as_of: Date | None,
    limit: int,
) -> list[PricePoint]:
    if as_of is None:
        return []
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            """
            SELECT date, COALESCE(adj_close, close) AS close, volume
            FROM prices_daily
            WHERE stock_code = ?
              AND date <= ?
            ORDER BY date DESC
            LIMIT ?
            """,
            [code, as_of.isoformat(), limit],
        ).fetchall()
    points = [
        PricePoint(date=Date.fromisoformat(str(day)), close=float(close), volume=int(volume))
        for day, close, volume in rows
    ]
    return list(reversed(points))


def _factor_values(code: str, as_of: Date | None) -> dict[str, float | None]:
    if as_of is None:
        return {"PER": None, "PBR": None, "ROE": None, "ROA": None}
    values = {
        "PER": calculate_per([code], as_of=as_of).get(code),
        "PBR": calculate_pbr([code], as_of=as_of).get(code),
        "ROE": calculate_roe([code], as_of=as_of).get(code),
        "ROA": calculate_roa([code], as_of=as_of).get(code),
    }
    return {key: _float_or_none(value) for key, value in values.items()}


def _factor_ranks(code: str, as_of: Date | None, market: str | None) -> dict[str, float | None]:
    if as_of is None or market is None:
        return {"PER": None, "PBR": None, "ROE": None}
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            """
            SELECT code
            FROM stocks
            WHERE market = ?
              AND listed_at <= ?
              AND (delisted_at IS NULL OR delisted_at > ?)
            """,
            [market, as_of.isoformat(), as_of.isoformat()],
        ).fetchall()
    codes = [str(row[0]).zfill(6) for row in rows]
    if code not in codes:
        codes.append(code)
    result: dict[str, float | None] = {}
    for factor_name, series in {
        "PER": calculate_per(codes, as_of=as_of),
        "PBR": calculate_pbr(codes, as_of=as_of),
        "ROE": calculate_roe(codes, as_of=as_of),
    }.items():
        ranks = series.rank(pct=True, ascending=factor_name in {"PER", "PBR"})
        result[factor_name] = _float_or_none(ranks.get(code))
    return result


def _local_activity(code: str) -> dict[str, Any]:
    path = Path(service_db_path)
    if not path.exists():
        return {"trade_count": 0, "latest_trade_at": None, "latest_journal_id": None}
    with sqlite3.connect(path) as conn:
        trade_row = conn.execute(
            """
            SELECT COUNT(*), MAX(executed_at)
            FROM trades
            WHERE stock_code = ?
            """,
            [code],
        ).fetchone()
        journal_row = conn.execute(
            """
            SELECT tj.id
            FROM trade_journal tj
            JOIN trades t ON t.id = tj.trade_id
            WHERE t.stock_code = ?
            ORDER BY tj.created_at DESC
            LIMIT 1
            """,
            [code],
        ).fetchone()
    return {
        "trade_count": int(trade_row[0] or 0) if trade_row else 0,
        "latest_trade_at": trade_row[1] if trade_row else None,
        "latest_journal_id": int(journal_row[0]) if journal_row else None,
    }


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return result
