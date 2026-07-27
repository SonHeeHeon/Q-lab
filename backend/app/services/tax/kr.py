"""Thin backend wrapper around ``research.backtest.tax_kr``.

Re-exports the classification/tax-estimate helpers as-is (research/ has no
DB dependency, so importing it here is safe — the reverse import direction,
research importing backend, is not allowed) and adds a DB-backed helper that
sums FIFO realized gains on 과세대상(etf_taxable) ETF sells for a calendar
year, across one or more accounts.
"""

from __future__ import annotations

from datetime import date as Date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services.performance.reconstruct import FilledTrade, realized_pnl_between
from research.backtest.tax_kr import classify_kr_instrument, estimate_sell_tax
from shared.db.models import Trade
from shared.domain.account import AccountType

__all__ = ["classify_kr_instrument", "estimate_sell_tax", "ytd_taxable_etf_gain"]


async def ytd_taxable_etf_gain(
    session: AsyncSession,
    account_types: list[AccountType],
    year: int,
) -> float:
    """Sum of FIFO realized gains on taxable-ETF (``etf_taxable``) sells filled
    within ``year`` (Jan 1..Dec 31), across ``account_types``. Can be negative.

    Mirrors how ``performance/service.py:_load_filled_trades`` queries filled
    trades, kept as a simpler inline query here since only the taxable-ETF
    subset and a fixed calendar-year window are needed.
    """
    result = await session.execute(
        select(Trade)
        .where(Trade.account_type.in_([account_type.value for account_type in account_types]))
        .where(Trade.filled_quantity > 0)
        .order_by(Trade.executed_at)
    )
    fills: list[FilledTrade] = []
    for trade in result.scalars():
        when = trade.filled_at or trade.executed_at
        price = trade.filled_price if trade.filled_price is not None else trade.price
        fills.append(
            FilledTrade(
                date=when.date(),
                code=trade.stock_code,
                side=str(trade.direction).upper(),
                qty=int(trade.filled_quantity),
                price=float(price),
                fees=float(trade.fees or 0),
                taxes=float(trade.taxes or 0),
            )
        )

    taxable_codes = {
        trade.code for trade in fills if classify_kr_instrument(trade.code) == "etf_taxable"
    }
    if not taxable_codes:
        return 0.0

    return realized_pnl_between(
        fills,
        Date(year, 1, 1),
        Date(year, 12, 31),
        code_filter=taxable_codes,
    )
