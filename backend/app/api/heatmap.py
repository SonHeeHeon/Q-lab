"""Market heatmap API."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import logging
import ssl
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import aiohttp
import certifi
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
    refresh_current_heatmap_snapshot,
)
from backend.app.core.config import settings
from shared.db.session import research_db_path

os.environ.setdefault("MPLCONFIGDIR", str(Path("/private/tmp/qlab-mplconfig")))

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])
logger = logging.getLogger(__name__)
NAVER_CHART_URL = "https://fchart.stock.naver.com/sise.nhn"


@dataclass(frozen=True, slots=True)
class CloseSnapshotRow:
    close: float
    volume: float
    change_pct: float
    market_cap: float | None = None


@dataclass(frozen=True, slots=True)
class CloseSnapshot:
    as_of: Date
    rows: dict[str, CloseSnapshotRow]


_close_snapshot_cache: dict[tuple[str, str], CloseSnapshot] = {}


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
    served_at: datetime | None = None
    market_session: str = "CLOSED"
    source: str = "research_db"
    price_basis: str = "DB_CLOSE"
    warning: str | None = None
    nodes: list[HeatmapNode]


@router.get("", response_model=ApiEnvelope[HeatmapResponse])
async def get_heatmap(
    market: Literal["KOSPI", "KOSDAQ"] = Query(default="KOSPI"),
    group_by: Literal["sector", "industry"] = Query(default="sector"),
    as_of: Date | None = Query(default=None),
    force_refresh: bool = Query(default=False),
) -> ApiEnvelope[HeatmapResponse]:
    session = get_market_session()
    snapshot_warning: str | None = None

    if as_of is None and not is_live_market_session(session):
        target_close_date = _target_close_date(_now())
        latest_db_date = await asyncio.to_thread(_latest_price_date, market)
        if force_refresh or latest_db_date is None or latest_db_date < target_close_date:
            meta = await asyncio.to_thread(_load_stock_meta, market)
            close_snapshot = await _load_naver_close_snapshot(
                market=market,
                target_date=target_close_date,
                codes=list(meta),
            )
            if close_snapshot is not None and close_snapshot.rows:
                response = await asyncio.to_thread(
                    _build_close_snapshot_heatmap,
                    market,
                    group_by,
                    close_snapshot,
                    session,
                    (
                        "research.db close prices were stale; using Naver close "
                        "snapshot."
                        if latest_db_date is None or latest_db_date < target_close_date
                        else None
                    ),
                )
                return ApiEnvelope(data=response, error=None)
            snapshot_warning = (
                "Latest close snapshot refresh failed; using research DB close prices."
            )

    if as_of is None and is_live_market_session(session):
        if force_refresh:
            snapshot = await refresh_current_heatmap_snapshot(market=market, force=True)
        else:
            snapshot = await get_live_heatmap_snapshot(
                market=market,
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
        if snapshot.source not in {"empty", "closed"} or snapshot.errors:
            snapshot_warning = _snapshot_warning(snapshot)

    response = await asyncio.to_thread(
        _build_heatmap,
        market,
        group_by,
        as_of,
        session,
        snapshot_warning,
    )
    return ApiEnvelope(data=response, error=None)


def _build_heatmap(
    market: str,
    group_by: str,
    as_of: Date | None,
    market_session: MarketSession | None = None,
    warning: str | None = None,
) -> HeatmapResponse:
    selected_date = as_of or _latest_price_date(market)
    served_at = _now()
    if selected_date is None:
        return HeatmapResponse(
            market=market,
            group_by=group_by,
            as_of=None,
            updated_at=None,
            served_at=served_at,
            market_session=(market_session or get_market_session()).value,
            source="research_db",
            price_basis="DB_CLOSE",
            warning=warning,
            nodes=[],
        )

    meta = _load_stock_meta(market)
    requested_date = as_of or _target_close_date(served_at)
    if as_of is None and selected_date < requested_date:
        warning = warning or (
            "research.db close prices are older than the target close date."
        )

    prices = _load_price_changes(selected_date)
    market_caps = _load_market_caps(selected_date, market)
    source = "research_db"
    price_basis = "DB_CLOSE"

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
        served_at=served_at,
        market_session=(market_session or get_market_session()).value,
        source=source,
        price_basis=price_basis,
        warning=warning,
        nodes=[root, *group_nodes, *stock_nodes],
    )


def _build_close_snapshot_heatmap(
    market: str,
    group_by: str,
    snapshot: CloseSnapshot,
    market_session: MarketSession | None = None,
    warning: str | None = None,
) -> HeatmapResponse:
    meta = _load_stock_meta(market)
    prices = _price_changes_from_close_snapshot(snapshot.rows)
    market_caps = {
        code: row.market_cap
        for code, row in snapshot.rows.items()
        if row.market_cap is not None
    }

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
                    "source": "naver:close_snapshot",
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
        meta={"market": market, "as_of": snapshot.as_of.isoformat()},
    )
    return HeatmapResponse(
        market=market,
        group_by=group_by,
        as_of=snapshot.as_of,
        updated_at=_historical_updated_at(snapshot.as_of),
        served_at=_now(),
        market_session=(market_session or get_market_session()).value,
        source="naver:close_snapshot",
        price_basis="NAVER_CLOSE",
        warning=warning,
        nodes=[root, *group_nodes, *stock_nodes],
    )


def _build_live_heatmap(
    market: str,
    group_by: str,
    snapshot: HeatmapSnapshot,
    as_of_override: Date | None = None,
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
        as_of=(
            as_of_override
            or (snapshot.updated_at.date() if snapshot.updated_at is not None else None)
        ),
        updated_at=snapshot.updated_at,
        served_at=_now(),
        market_session=snapshot.market_session.value,
        source=snapshot.source,
        price_basis=(
            "KIS_CLOSED_SNAPSHOT"
            if snapshot.source == "kis:closed_snapshot"
            else "REST_CURRENT_PRICE"
        ),
        warning=_snapshot_warning(snapshot) if snapshot.errors else None,
        nodes=[root, *group_nodes, *stock_nodes],
    )


def _snapshot_warning(snapshot: HeatmapSnapshot) -> str | None:
    if not snapshot.errors and snapshot.items:
        return None
    if snapshot.errors:
        sample = "; ".join(
            f"{code}: {message}" for code, message in list(snapshot.errors.items())[:3]
        )
        if snapshot.items:
            return (
                f"KIS current-price snapshot partially failed "
                f"({len(snapshot.errors)} symbols): {sample}"
            )
        return f"KIS current-price snapshot failed: {sample}"
    if snapshot.source == "kis:credentials_missing":
        return "KIS credentials are not configured for the heatmap snapshot account."
    return "KIS current-price snapshot returned no symbols; using research DB close prices."


def _latest_price_date(market: str) -> Date | None:
    sql = """
        SELECT MAX(p.date)
        FROM prices_daily AS p
        JOIN stocks AS s ON s.code = p.stock_code
        WHERE s.market = ?
          AND s.is_delisted = 0
    """
    with sqlite3.connect(research_db_path) as conn:
        row = conn.execute(sql, [market]).fetchone()
    if row is None or row[0] is None:
        return None
    return Date.fromisoformat(str(row[0]))


def _target_close_date(now: datetime | None = None) -> Date:
    current = (now or _now()).astimezone(ZoneInfo(settings.APSCHEDULER_TIMEZONE))
    regular_end = _parse_hhmm(settings.MARKET_SESSION_REGULAR_END)
    candidate = current.date()
    if current.time() < regular_end:
        candidate -= timedelta(days=1)
    return _previous_weekday(candidate)


def _previous_weekday(candidate: Date) -> Date:
    current = candidate
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _price_changes_from_close_snapshot(
    rows: dict[str, CloseSnapshotRow],
) -> dict[str, dict[str, float]]:
    return {
        code: {
            "close": row.close,
            "volume": row.volume,
            "change_pct": row.change_pct,
        }
        for code, row in rows.items()
    }


async def _load_naver_close_snapshot(
    *,
    market: str,
    target_date: Date,
    codes: list[str],
) -> CloseSnapshot | None:
    if not codes:
        return None

    for candidate in _recent_weekday_candidates(target_date, days=10):
        cache_key = (f"{market}:naver", candidate.isoformat())
        if cache_key in _close_snapshot_cache:
            return _close_snapshot_cache[cache_key]

        rows = await _load_naver_close_snapshot_for_date(candidate, codes)
        if rows:
            snapshot = CloseSnapshot(as_of=candidate, rows=rows)
            _close_snapshot_cache[cache_key] = snapshot
            return snapshot

    return None


def _recent_weekday_candidates(start: Date, *, days: int) -> list[Date]:
    result: list[Date] = []
    current = start
    for _ in range(days):
        if current.weekday() < 5:
            result.append(current)
        current -= timedelta(days=1)
    return result


async def _load_naver_close_snapshot_for_date(
    target_date: Date,
    codes: list[str],
) -> dict[str, CloseSnapshotRow]:
    rows: dict[str, CloseSnapshotRow] = {}
    timeout = aiohttp.ClientTimeout(total=8)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context, limit_per_host=16)
    semaphore = asyncio.Semaphore(16)
    count = max(30, (_now().date() - target_date).days + 20)

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 StockCollect heatmap"},
    ) as session:

        async def fetch_one(code: str) -> None:
            async with semaphore:
                try:
                    row = await _fetch_naver_close_row(
                        session,
                        code,
                        target_date,
                        count,
                    )
                except Exception as exc:
                    logger.debug(
                        "Naver close snapshot failed code=%s date=%s: %s",
                        code,
                        target_date,
                        exc,
                    )
                    return
                if row is not None:
                    rows[code] = row

        await asyncio.gather(*(fetch_one(code) for code in codes))

    return rows


async def _fetch_naver_close_row(
    session: aiohttp.ClientSession,
    code: str,
    target_date: Date,
    count: int,
) -> CloseSnapshotRow | None:
    async with session.get(
        NAVER_CHART_URL,
        params={
            "symbol": code,
            "timeframe": "day",
            "count": str(count),
            "requestType": "0",
        },
    ) as response:
        response.raise_for_status()
        body = await response.read()
    text = body.decode("euc-kr", errors="ignore")
    return _parse_naver_close_row(text, target_date)


def _parse_naver_close_row(
    xml_text: str,
    target_date: Date,
) -> CloseSnapshotRow | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    values: list[tuple[Date, float, float]] = []
    for item in root.iter("item"):
        raw_data = item.attrib.get("data", "")
        parts = raw_data.split("|")
        if len(parts) < 6:
            continue
        try:
            row_date = datetime.strptime(parts[0], "%Y%m%d").date()
            close = float(parts[4])
            volume = float(parts[5])
        except ValueError:
            continue
        if row_date <= target_date:
            values.append((row_date, close, volume))

    if not values:
        return None

    values.sort(key=lambda row: row[0])
    latest = values[-1]
    previous = values[-2] if len(values) >= 2 else latest
    previous_close = previous[1]
    change_pct = (
        (latest[1] / previous_close - 1.0) * 100.0
        if previous_close > 0
        else 0.0
    )
    return CloseSnapshotRow(
        close=latest[1],
        volume=latest[2],
        change_pct=change_pct,
    )


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


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.APSCHEDULER_TIMEZONE))


def _parse_hhmm(value: str) -> time:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        return time(int(hour_text), int(minute_text))
    except Exception:
        return time(15, 30)


def _pick(row: pd.Series, *keys: str) -> object | None:
    for key in keys:
        if key in row and pd.notna(row[key]):
            return row[key]
    return None
