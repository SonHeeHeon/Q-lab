"""Backfill Korean names + ISIN for the US universe (stocks_us) from Toss.

The ``stocks_us`` table only stores English names, so in-app Korean-language
search can't find US tickers (e.g. searching "램리서치" won't match LRCX).
Toss's Stock Info endpoint (``/api/v1/stocks``) returns each symbol's Korean
display name and ISIN; this batch fetches them in bulk and UPDATEs
``stocks_us.korean_name`` / ``stocks_us.isin``.

Robustness: Toss may not cover every ticker — misses keep NULL. Symbols are
fetched in chunks (the endpoint accepts up to 200 per call); a failed chunk is
logged and skipped so one failure never crashes the whole run. A gentle sleep
between chunks rate-limits the Stock Info group.

Not scheduler-registered — call ``run_us_names_sync()`` manually or wire it into
the scheduler separately (that file is owned elsewhere).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass

from backend.app.services.toss.rest_client import TossRestClient, TossRestError
from shared.db.session import research_db_path

logger = logging.getLogger(__name__)

# The Stock Info endpoint accepts up to 200 symbols per call; stay under that.
CHUNK_SIZE = 100
# Gentle rate-limit between chunks (Stock Info rate-limit group).
SLEEP_SECONDS = 0.3


@dataclass(slots=True)
class UsNamesSyncSummary:
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


async def run_us_names_sync(
    *,
    client: TossRestClient | None = None,
    db_path: str | None = None,
) -> UsNamesSyncSummary:
    """Populate stocks_us.korean_name / isin from Toss Stock Info.

    ``client`` / ``db_path`` are injectable for testing; both default to the
    production Toss client and research.db.
    """

    client = client or TossRestClient()
    path = db_path if db_path is not None else str(research_db_path)
    summary = UsNamesSyncSummary()

    with sqlite3.connect(path) as conn:
        tickers = [
            row[0]
            for row in conn.execute("SELECT ticker FROM stocks_us ORDER BY ticker")
        ]

    summary.total = len(tickers)
    if not tickers:
        logger.warning("us_names_sync: stocks_us has no tickers — nothing to do")
        return summary
    if not client.is_configured:
        logger.warning("us_names_sync: Toss client not configured — skipping")
        return summary

    for chunk in _chunks(tickers, CHUNK_SIZE):
        try:
            infos = await client.get_stock_infos(chunk)
        except TossRestError:
            summary.errors += 1
            logger.exception("us_names_sync: Toss stock-info fetch failed for a chunk")
            continue

        by_symbol = {info.symbol.upper(): info for info in infos if info.symbol}
        updates: list[tuple[str, str | None, str]] = []
        for ticker in chunk:
            info = by_symbol.get(ticker.upper())
            if info is None or not info.name:
                summary.missing += 1
                continue
            updates.append((info.name, info.isin, ticker))

        if updates:
            try:
                with sqlite3.connect(path) as conn:
                    conn.executemany(
                        "UPDATE stocks_us "
                        "SET korean_name = ?, isin = COALESCE(?, isin) "
                        "WHERE ticker = ?",
                        updates,
                    )
                    conn.commit()
                summary.updated += len(updates)
            except sqlite3.Error:
                summary.errors += 1
                logger.exception("us_names_sync: DB update failed for a chunk")

        await asyncio.sleep(SLEEP_SECONDS)

    logger.info("us_names_sync summary=%s", summary.to_dict())
    return summary


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
