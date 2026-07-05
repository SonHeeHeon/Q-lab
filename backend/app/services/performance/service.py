"""Async orchestration for paper/real/backtest performance.

Data-source priority for a live account:
1. ``portfolio_snapshots`` — actual broker-reported daily NAV (source of truth).
2. Reconstruction from filled ``trades`` + historical ``prices_daily`` when no
   snapshots exist yet (best-effort, assumes an initial-capital baseline).

The BACKTEST mode reads the persisted ``equity_curve.csv`` of the latest run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from research.backtest.metrics import Metrics, compute_metrics
from shared.db.models import PortfolioSnapshot, PriceDaily, Trade
from shared.domain.account import AccountType

from .backtest_curve import load_latest_backtest_curve
from .reconstruct import (
    FilledTrade,
    build_equity_curve,
    make_close_lookup,
    to_simulated_trades,
    total_return,
)

DEFAULT_INITIAL_CAPITAL = 100_000_000.0
_FILLED_STATUSES = ("FILLED", "PARTIALLY_FILLED", "PARTIAL")


@dataclass
class ModePerformance:
    """One mode's (paper/real/backtest) performance, ready for the API layer."""

    strategy: str
    mode: str  # PAPER | REAL | BACKTEST
    source: str  # BROKER_SNAPSHOT | RECONSTRUCTED | BACKTEST | EMPTY
    equity_curve: list[tuple[Date, float]]
    metrics: Metrics
    total_return: float
    initial_nav: float | None
    current_nav: float | None
    start_date: Date | None
    as_of: Date | None
    warnings: list[str] = field(default_factory=list)


def _empty(strategy: str, mode: str) -> ModePerformance:
    return ModePerformance(
        strategy=strategy,
        mode=mode,
        source="EMPTY",
        equity_curve=[],
        metrics=compute_metrics([], []),
        total_return=0.0,
        initial_nav=None,
        current_nav=None,
        start_date=None,
        as_of=None,
        warnings=["표시할 데이터가 아직 없습니다."],
    )


def load_backtest_performance(strategy: str) -> ModePerformance:
    """Latest backtest run's equity curve for ``strategy`` (reads report CSV)."""
    curve = load_latest_backtest_curve(strategy)
    if not curve:
        return _empty(strategy, "BACKTEST")
    metrics = compute_metrics(curve, [])
    return ModePerformance(
        strategy=strategy,
        mode="BACKTEST",
        source="BACKTEST",
        equity_curve=curve,
        metrics=metrics,
        total_return=total_return(curve),
        initial_nav=curve[0][1],
        current_nav=curve[-1][1],
        start_date=curve[0][0],
        as_of=curve[-1][0],
        warnings=[],
    )


async def load_account_performance(
    service_session: AsyncSession,
    research_session: AsyncSession,
    *,
    account_type: AccountType,
    strategy: str,
    initial_capital: float | None = None,
) -> ModePerformance:
    """Paper/real performance: prefer broker snapshots, else reconstruct."""
    capital = initial_capital or DEFAULT_INITIAL_CAPITAL
    mode = account_type.value

    snapshots = await _load_snapshots(service_session, account_type)
    fills = await _load_filled_trades(service_session, account_type)

    if snapshots:
        curve = [(row.date, float(row.nav)) for row in snapshots]
        metrics = compute_metrics(curve, to_simulated_trades(fills))
        return ModePerformance(
            strategy=strategy,
            mode=mode,
            source="BROKER_SNAPSHOT",
            equity_curve=curve,
            metrics=metrics,
            total_return=total_return(curve),
            initial_nav=curve[0][1],
            current_nav=curve[-1][1],
            start_date=curve[0][0],
            as_of=curve[-1][0],
            warnings=[],
        )

    if not fills:
        return _empty(strategy, mode)

    codes = sorted({trade.code for trade in fills})
    start = min(trade.date for trade in fills)
    price_rows = await _load_price_rows(research_session, codes, start)
    calendar = sorted({day for _, day, _ in price_rows})
    if not calendar:
        calendar = sorted({trade.date for trade in fills})
    lookup = make_close_lookup(price_rows)
    curve = build_equity_curve(fills, calendar, lookup, capital)
    metrics = compute_metrics(curve, to_simulated_trades(fills))
    return ModePerformance(
        strategy=strategy,
        mode=mode,
        source="RECONSTRUCTED",
        equity_curve=curve,
        metrics=metrics,
        total_return=total_return(curve),
        initial_nav=curve[0][1] if curve else capital,
        current_nav=curve[-1][1] if curve else None,
        start_date=curve[0][0] if curve else None,
        as_of=curve[-1][0] if curve else None,
        warnings=[
            "실측 NAV 스냅샷이 없어 체결 내역과 과거 종가로 재구성했습니다 "
            f"(초기 자본 {capital:,.0f}원 가정). 스냅샷이 쌓이면 실측값으로 대체됩니다."
        ],
    )


async def _load_snapshots(
    session: AsyncSession,
    account_type: AccountType,
) -> list[PortfolioSnapshot]:
    """Broker NAV snapshots for the account. Empty if the table is absent."""
    try:
        result = await session.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.account_type == account_type.value)
            .order_by(PortfolioSnapshot.date)
        )
        return list(result.scalars())
    except OperationalError:
        # Migration not yet applied — fall back to reconstruction.
        await session.rollback()
        return []


async def _load_filled_trades(
    session: AsyncSession,
    account_type: AccountType,
) -> list[FilledTrade]:
    result = await session.execute(
        select(Trade)
        .where(Trade.account_type == account_type.value)
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
    return fills


async def _load_price_rows(
    session: AsyncSession,
    codes: list[str],
    start: Date,
) -> list[tuple[str, Date, float]]:
    if not codes:
        return []
    close = func.coalesce(PriceDaily.adj_close, PriceDaily.close)
    result = await session.execute(
        select(PriceDaily.stock_code, PriceDaily.date, close)
        .where(PriceDaily.stock_code.in_(codes))
        .where(PriceDaily.date >= start)
        .order_by(PriceDaily.date)
    )
    return [(code, day, float(value)) for code, day, value in result.all()]
