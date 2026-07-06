"""Daily portfolio NAV snapshot recorder.

Records each active KIS account's broker-reported NAV into ``portfolio_snapshots``
after market close, so the performance feature's paper/real equity curves
accumulate real (source='BROKER') data over time instead of relying on the
trades+prices reconstruction fallback.

The ``upsert_snapshot`` core is DB-only and unit-tested; ``run_nav_snapshot``
wraps it with the live broker balance fetch (verified in production, like the
other batch jobs).
"""

from __future__ import annotations

import logging
from datetime import date as Date
from decimal import Decimal

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.services.kis.rest_client import KISRestClient
from shared.db.models import PortfolioSnapshot
from shared.db.session import service_session
from shared.domain.account import AccountType

logger = logging.getLogger(__name__)


def _dec(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


async def upsert_snapshot(
    session: AsyncSession,
    *,
    account_type: str,
    as_of: Date,
    nav: Decimal,
    cash: Decimal,
    holdings_value: Decimal,
    source: str = "BROKER",
) -> None:
    """Insert or update the (account_type, date) NAV snapshot."""
    stmt = insert(PortfolioSnapshot).values(
        account_type=account_type,
        date=as_of,
        nav=nav,
        cash=cash,
        holdings_value=holdings_value,
        source=source,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PortfolioSnapshot.account_type, PortfolioSnapshot.date],
        set_={
            "nav": stmt.excluded.nav,
            "cash": stmt.excluded.cash,
            "holdings_value": stmt.excluded.holdings_value,
            "source": stmt.excluded.source,
        },
    )
    await session.execute(stmt)


async def run_nav_snapshot(*, as_of: Date | None = None) -> int:
    """Record today's NAV for each active KIS account. Returns rows recorded."""
    snapshot_date = as_of or Date.today()
    client = KISRestClient()
    recorded = 0
    async with service_session() as session:
        for account_type in AccountType:
            try:
                if not settings.kis_account(account_type).is_active:
                    continue
                balance = await client.get_balance(account_type)
                summary = balance.summary
                await upsert_snapshot(
                    session,
                    account_type=account_type.value,
                    as_of=snapshot_date,
                    nav=_dec(summary.total_evaluation_amount),
                    cash=_dec(summary.cash_amount or summary.cash_krw),
                    holdings_value=_dec(summary.stock_evaluation_amount),
                )
                recorded += 1
            except Exception:
                logger.exception(
                    "nav snapshot failed account=%s", account_type.value
                )
        await session.commit()
    logger.info("nav snapshot recorded=%s date=%s", recorded, snapshot_date)
    return recorded
