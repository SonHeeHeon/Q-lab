"""Backfill GICS sector + industry for the US universe (stocks_us) from yfinance.

The ``stocks_us`` table is seeded with only ticker/name (sector + industry are
NULL), so the NASDAQ100 heatmap's sector grouping collapses into a single
"Unknown" blob. yfinance exposes each symbol's GICS classification via
``yf.Ticker(t).info`` (``sector`` / ``industry``); this batch fetches them one
ticker at a time and UPDATEs ``stocks_us.sector`` / ``stocks_us.industry``.

Robustness: yfinance may not cover (or may rate-limit) every ticker — a failed
fetch is logged and skipped so one failure never crashes the whole run, and a
symbol with neither sector nor industry keeps its existing NULL. A gentle sleep
between tickers rate-limits the ``.info`` endpoint. Progress is flushed to the
DB in batches so a long run persists partial results.

Not scheduler-registered — this is a one-shot backfill. Call
``run_us_sector_sync()`` manually (or wire it into the scheduler separately in
the file that owns scheduling).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from typing import Callable

from shared.db.session import research_db_path

logger = logging.getLogger(__name__)

# Gentle rate-limit between per-ticker ``.info`` fetches (yfinance is scrape-based
# and will throttle bursty callers).
SLEEP_SECONDS = 0.5
# Flush accumulated UPDATEs to the DB every N tickers so a long run persists
# partial progress even if it's interrupted.
FLUSH_EVERY = 20

# A callable that maps a ticker -> its info dict (or None). Injectable for tests.
FetchInfo = Callable[[str], "dict | None"]


@dataclass(slots=True)
class UsSectorSyncSummary:
    total: int = 0
    updated: int = 0
    missing: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "updated": self.updated,
            "missing": self.missing,
            "errors": self.errors,
        }


def _default_fetch_info(ticker: str) -> dict | None:
    """Fetch a single ticker's info dict via yfinance.

    Imported lazily so the module (and its importers, e.g. the heatmap API)
    don't pay the yfinance import cost unless a sync actually runs.
    """

    import warnings

    import yfinance as yf

    warnings.filterwarnings("ignore")
    return yf.Ticker(ticker).info


async def run_us_sector_sync(
    *,
    fetch_info: FetchInfo | None = None,
    db_path: str | None = None,
    sleep_seconds: float = SLEEP_SECONDS,
) -> UsSectorSyncSummary:
    """Populate stocks_us.sector / industry from yfinance ``.info``.

    ``fetch_info`` / ``db_path`` are injectable for testing; both default to the
    production yfinance fetch and research.db. ``fetch_info`` is a sync callable
    ``(ticker) -> info-dict | None`` and is always run in a worker thread.
    """

    fetch = fetch_info or _default_fetch_info
    path = db_path if db_path is not None else str(research_db_path)
    summary = UsSectorSyncSummary()

    with sqlite3.connect(path) as conn:
        tickers = [
            row[0]
            for row in conn.execute("SELECT ticker FROM stocks_us ORDER BY ticker")
        ]

    summary.total = len(tickers)
    if not tickers:
        logger.warning("us_sector_sync: stocks_us has no tickers — nothing to do")
        return summary

    pending: list[tuple[str | None, str | None, str]] = []
    for index, ticker in enumerate(tickers, start=1):
        try:
            info = await asyncio.to_thread(fetch, ticker)
        except Exception:
            summary.errors += 1
            logger.exception("us_sector_sync: info fetch failed ticker=%s", ticker)
            continue

        sector = (info or {}).get("sector") or None
        industry = (info or {}).get("industry") or None
        if sector is None and industry is None:
            summary.missing += 1
        else:
            pending.append((sector, industry, ticker))

        if len(pending) >= FLUSH_EVERY:
            summary.updated += _flush(path, pending, summary)
            pending = []

        if sleep_seconds > 0 and index < len(tickers):
            await asyncio.sleep(sleep_seconds)

    if pending:
        summary.updated += _flush(path, pending, summary)

    logger.info("us_sector_sync summary=%s", summary.to_dict())
    return summary


def _flush(
    path: str,
    updates: list[tuple[str | None, str | None, str]],
    summary: UsSectorSyncSummary,
) -> int:
    """Persist a batch of (sector, industry, ticker) UPDATEs; return #applied.

    COALESCE keeps an existing non-NULL value when the fetched field is NULL, so
    a partial hit (sector but no industry) never clobbers prior data. A failed
    flush is logged and counted as one error — the caller drops the batch.
    """

    try:
        with sqlite3.connect(path) as conn:
            conn.executemany(
                "UPDATE stocks_us "
                "SET sector = COALESCE(?, sector), "
                "    industry = COALESCE(?, industry) "
                "WHERE ticker = ?",
                updates,
            )
            conn.commit()
        return len(updates)
    except sqlite3.Error:
        summary.errors += 1
        logger.exception("us_sector_sync: DB update failed for a batch")
        return 0
