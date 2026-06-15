"""Market heatmap API."""

from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import date as Date
from datetime import datetime, time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.kis.market_snapshot import (
    HeatmapSnapshot,
    MarketSession,
    get_live_heatmap_snapshot,
    get_market_session,
    is_live_market_session,
)
from backend.app.core.config import settings
from shared.db.session import research_db_path

os.environ.setdefault("MPLCONFIGDIR", str(Path("/private/tmp/qlab-mplconfig")))

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])


class HeatmapNode(BaseModel):
    id: str
    parent_id: str | None
    label: str
    level: Literal["root", "group", "stock"]
    size: float
    color_value: float
    meta: dict[str, object]


class HeatmapResponse(BaseModel):
    market: str
    group_by: str
    as_of: Date | None
    updated_at: datetime | None = None
    market_session: str = "CLOSED"
    source: str = "research_db"
    nodes: list[HeatmapNode]


@router.get("", response_model=ApiEnvelope[HeatmapResponse])
async def get_heatmap(
    market: Literal["KOSPI", "KOSDAQ"] = Query(default="KOSPI"),
    group_by: Literal["sector", "industry"] = Query(default="sector"),
    as_of: Date | None = Query(default=None),
) -> ApiEnvelope[HeatmapResponse]:
    session = get_market_session()
    if (
        market == "KOSPI"
        and as_of is None
        and is_live_market_session(session)
    ):
        snapshot = await get_live_heatmap_snapshot(
            refresh_if_stale=settings.MARKET_SNAPSHOT_AUTOSTART
        )
        if snapshot.items:
            response = await asyncio.to_thread(
                _build_live_heatmap,
                market,
                group_by,
                snapshot,
            )
            return ApiEnvelope(data=response, error=None)

    response = await asyncio.to_thread(
        _build_heatmap,
        market,
        group_by,
        as_of,
        session,
    )
    return ApiEnvelope(data=response, error=None)


def _build_heatmap(
    market: str,
    group_by: str,
    as_of: Date | None,
    market_session: MarketSession | None = None,
) -> HeatmapResponse:
    selected_date = as_of or _latest_price_date()
    if selected_date is None:
        return HeatmapResponse(
            market=market,
            group_by=group_by,
            as_of=None,
            updated_at=None,
            market_session=(market_session or get_market_session()).value,
            source="research_db",
            nodes=[],
        )

    meta = _load_stock_meta(market)
    prices = _load_price_changes(selected_date)
    market_caps = _load_market_caps(selected_date, market)

    stock_nodes: list[HeatmapNode] = []
    for code, stock_meta in meta.items():
        price_row = prices.get(code)
        if price_row is None:
            continue
        market_cap = market_caps.get(code)
        fallback_size = price_row["close"] * max(price_row["volume"], 1)
        size = float(market_cap or fallback_size)
        group_label = stock_meta.get(group_by) or "Unknown"
        stock_nodes.append(
            HeatmapNode(
                id=f"stock:{code}",
                parent_id=f"group:{group_label}",
                label=f"{code} {stock_meta['name']}",
                level="stock",
                size=size,
                color_value=float(price_row["change_pct"]),
                meta={
                    "code": code,
                    "name": stock_meta["name"],
                    "market": stock_meta["market"],
                    "sector": stock_meta.get("sector"),
                    "industry": stock_meta.get("industry"),
                    "market_cap": market_cap,
                    "close": price_row["close"],
                    "volume": price_row["volume"],
                },
            )
        )

    group_nodes = _group_nodes(stock_nodes)
    root_size = sum(node.size for node in stock_nodes)
    root_color = _weighted_color(stock_nodes)
    root = HeatmapNode(
        id="root",
        parent_id=None,
        label=market,
        level="root",
        size=root_size,
        color_value=root_color,
        meta={"market": market, "as_of": selected_date.isoformat()},
    )
    return HeatmapResponse(
        market=market,
        group_by=group_by,
        as_of=selected_date,
        updated_at=_historical_updated_at(selected_date),
        market_session=(market_session or get_market_session()).value,
        source="research_db",
        nodes=[root, *group_nodes, *stock_nodes],
    )


def _build_live_heatmap(
    market: str,
    group_by: str,
    snapshot: HeatmapSnapshot,
) -> HeatmapResponse:
    meta = _load_stock_meta(market)

    stock_nodes: list[HeatmapNode] = []
    for code, item in snapshot.items.items():
        stock_meta = meta.get(code) or {
            "name": item.name or code,
            "market": market,
            "sector": None,
            "industry": None,
        }
        fallback_size = item.current_price * max(item.volume, 1)
        size = float(item.market_cap or fallback_size)
        group_label = stock_meta.get(group_by) or "Unknown"
        stock_nodes.append(
            HeatmapNode(
                id=f"stock:{code}",
                parent_id=f"group:{group_label}",
                label=f"{code} {stock_meta['name']}",
                level="stock",
                size=size,
                color_value=float(item.change_pct),
                meta={
                    "code": code,
                    "name": stock_meta["name"],
                    "market": stock_meta["market"],
                    "sector": stock_meta.get("sector"),
                    "industry": stock_meta.get("industry"),
                    "market_cap": item.market_cap,
                    "close": item.current_price,
                    "current_price": item.current_price,
                    "previous_close": item.previous_close,
                    "change_amount": item.change_amount,
                    "change_pct": item.change_pct,
                    "volume": item.volume,
                    "source": snapshot.source,
                    "updated_at": (
                        snapshot.updated_at.isoformat()
                        if snapshot.updated_at is not None
                        else None
                    ),
                },
            )
        )

    group_nodes = _group_nodes(stock_nodes)
    root_size = sum(node.size for node in stock_nodes)
    root_color = _weighted_color(stock_nodes)
    root = HeatmapNode(
        id="root",
        parent_id=None,
        label=market,
        level="root",
        size=root_size,
        color_value=root_color,
        meta={
            "market": market,
            "source": snapshot.source,
            "errors": len(snapshot.errors),
        },
    )
    return HeatmapResponse(
        market=market,
        group_by=group_by,
        as_of=snapshot.updated_at.date() if snapshot.updated_at is not None else None,
        updated_at=snapshot.updated_at,
        market_session=snapshot.market_session.value,
        source=snapshot.source,
        nodes=[root, *group_nodes, *stock_nodes],
    )


def _latest_price_date() -> Date | None:
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute("SELECT MAX(date) FROM prices_daily").fetchone()
    if row is None or row[0] is None:
        return None
    return Date.fromisoformat(str(row[0]))


def _load_stock_meta(market: str) -> dict[str, dict[str, str | None]]:
    sql = """
        SELECT code, name, market, sector, industry
        FROM stocks
        WHERE market = ?
          AND is_delisted = 0
        ORDER BY code
    """
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(sql, [market]).fetchall()
    return {
        str(code).zfill(6): {
            "name": name,
            "market": row_market,
            "sector": sector,
            "industry": industry,
        }
        for code, name, row_market, sector, industry in rows
    }


def _load_price_changes(as_of: Date) -> dict[str, dict[str, float]]:
    sql = """
        SELECT stock_code, date, close, volume
        FROM (
            SELECT
                stock_code,
                date,
                COALESCE(adj_close, close) AS close,
                volume,
                ROW_NUMBER() OVER (
                    PARTITION BY stock_code
                    ORDER BY date DESC
                ) AS rn
            FROM prices_daily
            WHERE date <= ?
        )
        WHERE rn <= 2
        ORDER BY stock_code, date DESC
    """
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(sql, [as_of.isoformat()]).fetchall()

    grouped: dict[str, list[tuple[str, float, float]]] = {}
    for code, row_date, close, volume in rows:
        grouped.setdefault(str(code).zfill(6), []).append(
            (str(row_date), float(close), float(volume))
        )

    result: dict[str, dict[str, float]] = {}
    for code, values in grouped.items():
        latest = values[0]
        previous = values[1] if len(values) > 1 else latest
        previous_close = previous[1]
        change_pct = (
            (latest[1] / previous_close - 1.0) * 100.0
            if previous_close > 0
            else 0.0
        )
        result[code] = {
            "close": latest[1],
            "volume": latest[2],
            "change_pct": change_pct,
        }
    return result


def _load_market_caps(as_of: Date, market: str) -> dict[str, float]:
    try:
        from pykrx import stock

        frame = stock.get_market_cap_by_ticker(
            as_of.strftime("%Y%m%d"),
            market=market,
        )
    except Exception:
        return {}

    if frame is None or frame.empty or "시가총액" not in frame.columns:
        return {}

    values: dict[str, float] = {}
    for code, row in frame.iterrows():
        market_cap = row.get("시가총액")
        if pd.notna(market_cap):
            values[str(code).zfill(6)] = float(market_cap)
    return values


def _group_nodes(stock_nodes: list[HeatmapNode]) -> list[HeatmapNode]:
    groups: dict[str, list[HeatmapNode]] = {}
    for node in stock_nodes:
        group_id = node.parent_id or "group:Unknown"
        groups.setdefault(group_id, []).append(node)

    result = []
    for group_id, children in sorted(groups.items()):
        label = group_id.removeprefix("group:")
        result.append(
            HeatmapNode(
                id=group_id,
                parent_id="root",
                label=label,
                level="group",
                size=sum(child.size for child in children),
                color_value=_weighted_color(children),
                meta={"count": len(children)},
            )
        )
    return result


def _weighted_color(nodes: list[HeatmapNode]) -> float:
    total_size = sum(node.size for node in nodes)
    if total_size <= 0:
        return 0.0
    return sum(node.color_value * node.size for node in nodes) / total_size


def _historical_updated_at(selected_date: Date) -> datetime:
    timezone = ZoneInfo(settings.APSCHEDULER_TIMEZONE)
    return datetime.combine(selected_date, time(15, 30), tzinfo=timezone)
