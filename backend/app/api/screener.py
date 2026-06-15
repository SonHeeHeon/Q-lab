"""Factor screener API."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date as Date
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.app.schemas.portfolio import ApiEnvelope
from research.backtest.engine import get_universe, score_stocks
from research.factors.common import table_exists
from shared.db.session import research_db_path
from shared.domain.strategy import FactorWeight

router = APIRouter(prefix="/api/screener", tags=["screener"])


class ScreenerRow(BaseModel):
    code: str
    name: str | None
    market: str | None
    sector: str | None
    industry: str | None
    score: float
    factors: dict[str, float | None]


class ScreenerResponse(BaseModel):
    as_of: Date
    universe: str
    top_n: int
    rows: list[ScreenerRow]
    warnings: list[str] = Field(default_factory=list)


@router.get("", response_model=ApiEnvelope[ScreenerResponse])
async def run_screener(
    universe: Literal["KOSPI200", "KOSDAQ150", "KOSPI_ALL", "KOSDAQ_ALL", "NASDAQ100"] = Query(default="KOSPI200"),
    as_of: Date | None = Query(default=None),
    top_n: int = Query(default=30, ge=1, le=300),
    per_weight: float = Query(default=-1.0),
    pbr_weight: float = Query(default=-1.0),
    roe_weight: float = Query(default=1.0),
) -> ApiEnvelope[ScreenerResponse]:
    selected_date = as_of or await asyncio.to_thread(_latest_price_date, universe)
    response = await asyncio.to_thread(
        _run_screener,
        universe,
        selected_date,
        top_n,
        per_weight,
        pbr_weight,
        roe_weight,
    )
    return ApiEnvelope(data=response, error=None)


def _run_screener(
    universe: str,
    as_of: Date,
    top_n: int,
    per_weight: float,
    pbr_weight: float,
    roe_weight: float,
) -> ScreenerResponse:
    warnings: list[str] = []
    factors = [
        FactorWeight(factor="PER", weight=per_weight, transform="ZSCORE"),
        FactorWeight(factor="PBR", weight=pbr_weight, transform="ZSCORE"),
        FactorWeight(factor="ROE", weight=roe_weight, transform="ZSCORE"),
    ]
    codes = get_universe(universe, as_of=as_of)
    scored = score_stocks(
        codes,
        factors,
        as_of=as_of,
        warnings=warnings,
    ).head(top_n)
    meta = _load_meta(list(scored.index), universe)
    rows: list[ScreenerRow] = []
    for code, row in scored.iterrows():
        stock_meta = meta.get(str(code), {})
        factor_values = {
            key: _float_or_none(row.get(key))
            for key in ["PER", "PBR", "ROE"]
            if key in scored.columns
        }
        rows.append(
            ScreenerRow(
                code=str(code),
                name=stock_meta.get("name"),
                market=stock_meta.get("market"),
                sector=stock_meta.get("sector"),
                industry=stock_meta.get("industry"),
                score=float(row["score"]),
                factors=factor_values,
            )
        )
    return ScreenerResponse(
        as_of=as_of,
        universe=universe,
        top_n=top_n,
        rows=rows,
        warnings=warnings,
    )


def _latest_price_date(universe: str) -> Date:
    table = "prices_daily_us" if universe == "NASDAQ100" else "prices_daily"
    with sqlite3.connect(research_db_path) as conn:
        if not table_exists(conn, table):
            return Date.today()
        row = conn.execute(f"SELECT MAX(date) FROM {table}").fetchone()
    if row is None or row[0] is None:
        return Date.today()
    return Date.fromisoformat(str(row[0]))


def _load_meta(codes: list[str], universe: str) -> dict[str, dict[str, str | None]]:
    if not codes:
        return {}
    placeholders = ",".join("?" for _ in codes)
    if universe == "NASDAQ100":
        sql = f"""
            SELECT ticker, name, exchange, sector, industry
            FROM stocks_us
            WHERE ticker IN ({placeholders})
        """
        with sqlite3.connect(research_db_path) as conn:
            rows = conn.execute(sql, codes).fetchall()
        return {
            str(code): {
                "name": name,
                "market": exchange,
                "sector": sector,
                "industry": industry,
            }
            for code, name, exchange, sector, industry in rows
        }

    sql = f"""
        SELECT code, name, market, sector, industry
        FROM stocks
        WHERE code IN ({placeholders})
    """
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(sql, codes).fetchall()
    return {
        str(code).zfill(6): {
            "name": name,
            "market": market,
            "sector": sector,
            "industry": industry,
        }
        for code, name, market, sector, industry in rows
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
