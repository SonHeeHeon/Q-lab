"""Nightly incremental ingestion into research.db (prices/caps/flows/indices).

Keeps the factor inputs current so daily scoring and the in-app Backtest Lab
include the latest trading day. Each dataset resumes from its own last loaded
date (minus a small overlap — inserts are ON CONFLICT IGNORE, so overlap is
harmless). pykrx endpoints require KRX data-portal login; credentials come
from settings (KRX_ID / KRX_PW) and are pushed into the process environment
where pykrx reads them. Never log the credential values.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import date as Date
from datetime import timedelta

from backend.app.core.config import settings
from research.data_ingestion.etf_loader import update_us_prices_incremental
from research.data_ingestion.macro_loader import update_macro
from research.data_ingestion.pykrx_loader import (
    update_investor_flows,
    update_market_caps,
    update_market_indices,
    update_prices,
)
from shared.db.session import research_db_path

logger = logging.getLogger(__name__)

DEFAULT_OVERLAP_DAYS = 5


@dataclass(slots=True)
class DataSyncSummary:
    prices: int = 0
    market_caps: int = 0
    investor_flows: int = 0
    market_indices: int = 0
    us_prices: int = 0
    macro: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "prices": self.prices,
            "market_caps": self.market_caps,
            "investor_flows": self.investor_flows,
            "market_indices": self.market_indices,
            "us_prices": self.us_prices,
            "macro": self.macro,
            "errors": self.errors,
        }


async def run_data_sync(
    *,
    end: Date | None = None,
    overlap_days: int = DEFAULT_OVERLAP_DAYS,
) -> DataSyncSummary:
    """Incrementally ingest prices, market caps, investor flows, and indices."""

    _ensure_krx_env()
    today = end or Date.today()
    summary = DataSyncSummary()

    with sqlite3.connect(research_db_path) as conn:
        codes = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT stock_code FROM prices_daily ORDER BY stock_code"
            )
        ]
        # Per-instrument MIN(MAX(date)) so a single lagging symbol's gap is
        # covered rather than masked by the freshest symbol (same class of bug
        # as the market_index gap below, but per stock_code / ticker).
        price_start = _incremental_start(
            conn, "prices_daily", today, overlap_days, group_column="stock_code"
        )
        caps_start = _incremental_start(
            conn, "market_caps", today, overlap_days,
            fallback=price_start, group_column="stock_code",
        )
        flows_start = _incremental_start(
            conn, "investor_flows_daily", today, overlap_days,
            fallback=price_start, group_column="stock_code",
        )
        # market_index is shared by KOSPI/KOSDAQ (pykrx) *and* macro series
        # (SP500/US10Y/USDKRW/VIX, via macro_loader) under different
        # index_code values. An unscoped MAX(date) over the whole table can
        # be dragged forward by the macro rows even when KOSPI/KOSDAQ have
        # fallen behind (e.g. a transient pykrx failure), which would then
        # skip the actual gap forever. Scope this to the KR index codes that
        # update_market_indices() actually manages.
        index_start = _incremental_start(
            conn,
            "market_index",
            today,
            overlap_days,
            fallback=price_start,
            where="index_code IN ('KOSPI', 'KOSDAQ')",
        )
        us_start = _incremental_start(
            conn, "prices_daily_us", today, overlap_days,
            fallback=price_start, group_column="ticker",
        )

    if not codes:
        logger.warning(
            "data_sync: prices_daily has no codes — run the bulk loaders first"
        )
        return summary

    try:
        result = await update_prices(codes, start=price_start, end=today)
        summary.prices = result.requested
    except Exception:
        summary.errors += 1
        logger.exception("data_sync: price update failed")

    try:
        result = await update_market_caps(codes, start=caps_start, end=today)
        summary.market_caps = result.requested
    except Exception:
        summary.errors += 1
        logger.exception("data_sync: market cap update failed")

    try:
        result = await update_investor_flows(codes, start=flows_start, end=today)
        summary.investor_flows = result.requested
    except Exception:
        summary.errors += 1
        logger.exception("data_sync: investor flow update failed")

    try:
        results = await update_market_indices(start=index_start, end=today)
        summary.market_indices = sum(item.requested for item in results)
    except Exception:
        summary.errors += 1
        logger.exception("data_sync: market index update failed")

    try:
        result = await update_us_prices_incremental(start=us_start, end=today)
        summary.us_prices = result.requested
    except Exception:
        summary.errors += 1
        logger.exception("data_sync: us price update failed")

    try:
        macro_result = await update_macro(start=index_start, end=today)
        summary.macro = macro_result.total
    except Exception:
        summary.errors += 1
        logger.exception("data_sync: macro update failed")

    logger.info("data_sync summary=%s", summary.to_dict())
    return summary


def _incremental_start(
    conn: sqlite3.Connection,
    table: str,
    today: Date,
    overlap_days: int,
    *,
    fallback: Date | None = None,
    where: str | None = None,
    group_column: str | None = None,
) -> Date:
    """Resume from the table's last date minus overlap.

    Missing/empty table → ``fallback`` (usually the prices start) so a
    brand-new dataset backfills from known coverage instead of silently
    syncing only the last few days.

    ``where`` optionally scopes the MAX(date) lookup (e.g. to a subset of
    index_code values) for tables shared by multiple datasets with different
    sync cadences, so one dataset's freshness can't mask another's gap.

    ``group_column`` makes the resume date the MINIMUM over per-instrument
    MAX(date) (e.g. per stock_code / ticker). Without it, an unscoped
    MAX(date) is dragged forward by whichever instrument is freshest, so a
    single lagging symbol's gap (LRCX stuck at 06-09 while ETFs reached 07-06)
    is skipped forever. With it, the most-stale instrument's gap is covered.
    Loaders are idempotent (ON CONFLICT IGNORE) so re-fetching fresh symbols
    is harmless.
    """
    try:
        if group_column:
            query = (
                f"SELECT MIN(m) FROM (SELECT MAX(date) AS m FROM {table}"
                + (f" WHERE {where}" if where else "")
                + f" GROUP BY {group_column})"
            )
        else:
            query = f"SELECT MAX(date) FROM {table}"
            if where:
                query += f" WHERE {where}"
        row = conn.execute(query).fetchone()
        last = Date.fromisoformat(str(row[0])) if row and row[0] else None
    except sqlite3.Error:
        last = None
    if last is not None:
        return last - timedelta(days=overlap_days)
    if fallback is not None:
        return fallback
    return today - timedelta(days=overlap_days)


def _ensure_krx_env() -> None:
    """Expose KRX credentials to pykrx via the environment (values not logged)."""
    if settings.KRX_ID and "KRX_ID" not in os.environ:
        os.environ["KRX_ID"] = settings.KRX_ID
    secret = settings.KRX_PW.get_secret_value()
    if secret and "KRX_PW" not in os.environ:
        os.environ["KRX_PW"] = secret
