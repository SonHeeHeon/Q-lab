"""Pure equity-curve reconstruction from filled trades + historical closes.

These helpers are deliberately free of DB/HTTP dependencies so they can be
unit-tested with in-memory fixtures — mirroring the pure-function test style of
``backend/tests/test_api_portfolio.py`` (which imports ``_unified_response``).

A reconstructed curve assumes a starting cash baseline (``initial_capital``)
because ``trades`` records no opening deposit. It is a best-effort fallback used
only until real broker NAV snapshots (``portfolio_snapshots``) accumulate.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date as Date

from research.backtest.simulator import SimulatedTrade


@dataclass(frozen=True)
class FilledTrade:
    """A filled (or partially filled) execution reduced to what a curve needs."""

    date: Date
    code: str
    side: str  # "BUY" | "SELL"
    qty: int
    price: float
    fees: float = 0.0
    taxes: float = 0.0

    @property
    def cash_flow(self) -> float:
        """Positive for sell proceeds, negative for buy cash usage."""
        gross = self.price * self.qty
        if self.side.upper() == "BUY":
            return -(gross + self.fees + self.taxes)
        return gross - self.fees - self.taxes

    @property
    def notional(self) -> float:
        return self.price * self.qty

    @property
    def signed_qty(self) -> int:
        return self.qty if self.side.upper() == "BUY" else -self.qty


CloseLookup = Callable[[str, Date], float | None]


def make_close_lookup(rows: Iterable[tuple[str, Date, float]]) -> CloseLookup:
    """Build a ``close_on_or_before(code, day)`` accessor from price rows.

    ``rows`` is an iterable of ``(code, date, close)``. The returned callable
    forward-fills: it yields the most recent close on or before ``day`` (so a
    holiday/half-day without a bar keeps the last known price, matching the
    backtest engine's forward-fill behaviour).
    """
    by_code: dict[str, list[tuple[Date, float]]] = defaultdict(list)
    for code, day, close in rows:
        by_code[code].append((day, float(close)))
    for code in by_code:
        by_code[code].sort(key=lambda item: item[0])
    dates_only: dict[str, list[Date]] = {
        code: [day for day, _ in seq] for code, seq in by_code.items()
    }

    def close_on_or_before(code: str, day: Date) -> float | None:
        seq = by_code.get(code)
        if not seq:
            return None
        idx = bisect_right(dates_only[code], day) - 1
        if idx < 0:
            return None
        return seq[idx][1]

    return close_on_or_before


def build_equity_curve(
    trades: Sequence[FilledTrade],
    calendar: Sequence[Date],
    close_on_or_before: CloseLookup,
    initial_capital: float,
) -> list[tuple[Date, float]]:
    """Reconstruct a daily NAV curve over ``calendar``.

    NAV(day) = cash + Σ position_qty × close(code, day), where cash starts at
    ``initial_capital`` and each filled trade's cash flow is applied on its date.
    """
    trades_by_date: dict[Date, list[FilledTrade]] = defaultdict(list)
    for trade in trades:
        trades_by_date[trade.date].append(trade)

    positions: dict[str, int] = defaultdict(int)
    cash = float(initial_capital)
    curve: list[tuple[Date, float]] = []

    for day in calendar:
        for trade in trades_by_date.get(day, ()):
            cash += trade.cash_flow
            positions[trade.code] += trade.signed_qty
        holdings_value = 0.0
        for code, qty in positions.items():
            if qty <= 0:
                continue
            price = close_on_or_before(code, day)
            if price is not None:
                holdings_value += qty * price
        curve.append((day, cash + holdings_value))

    return curve


def to_simulated_trades(trades: Iterable[FilledTrade]) -> list[SimulatedTrade]:
    """Adapt filled trades to ``SimulatedTrade`` so ``compute_metrics`` (the same
    function the backtest uses) can derive win-rate / holding / turnover — keeping
    paper/real metrics directly comparable to the backtest's."""
    return [
        SimulatedTrade(
            date=trade.date,
            code=trade.code,
            side=trade.side.upper(),
            qty=trade.qty,
            price=trade.price,
            notional=trade.notional,
            commission=trade.fees,
            tax=trade.taxes,
            slippage_bps=0.0,
            cash_flow=trade.cash_flow,
        )
        for trade in trades
    ]


def total_return(curve: Sequence[tuple[Date, float]]) -> float:
    """Cumulative return over the curve; 0.0 for an empty/degenerate curve."""
    if not curve:
        return 0.0
    first = curve[0][1]
    last = curve[-1][1]
    return (last / first - 1.0) if first > 0 else 0.0


def realized_pnl_on(trades: Sequence[FilledTrade], day: Date) -> float:
    """FIFO realized PnL (fees/taxes included) from sells filled on ``day``.

    Walks the full fill history to build cost-basis lots, then sums the realized
    profit/loss of every sell executed on ``day``. Sells without a matching lot
    (position opened before trade history begins) are skipped rather than
    guessed. Mirrors the FIFO matching in research.backtest.metrics.
    """
    lots: dict[str, deque[tuple[int, float]]] = defaultdict(deque)
    realized = 0.0
    for trade in sorted(trades, key=lambda item: item.date):
        if trade.qty <= 0:
            continue
        if trade.side.upper() == "BUY":
            cost_per_share = -trade.cash_flow / trade.qty
            lots[trade.code].append((trade.qty, cost_per_share))
            continue
        remaining = trade.qty
        proceeds_per_share = trade.cash_flow / trade.qty
        while remaining > 0 and lots[trade.code]:
            lot_qty, cost_per_share = lots[trade.code].popleft()
            matched = min(remaining, lot_qty)
            if trade.date == day:
                realized += (proceeds_per_share - cost_per_share) * matched
            remaining -= matched
            if lot_qty > matched:
                lots[trade.code].appendleft((lot_qty - matched, cost_per_share))
    return realized


def realized_pnl_between(
    trades: Sequence[FilledTrade],
    start_day: Date,
    end_day: Date,
    *,
    code_filter: set[str] | None = None,
) -> float:
    """FIFO realized PnL (fees/taxes included) from sells filled within
    ``[start_day, end_day]`` (inclusive), optionally restricted to codes in
    ``code_filter``.

    Walks the full fill history across all codes (not just filtered ones) to
    build correct FIFO cost-basis lots — filtering trades before matching
    would corrupt lot ordering for a code — then sums the realized
    profit/loss of sells that both fall inside the date window and pass the
    code filter. Mirrors the FIFO matching in ``realized_pnl_on``.
    """
    lots: dict[str, deque[tuple[int, float]]] = defaultdict(deque)
    realized = 0.0
    for trade in sorted(trades, key=lambda item: item.date):
        if trade.qty <= 0:
            continue
        if trade.side.upper() == "BUY":
            cost_per_share = -trade.cash_flow / trade.qty
            lots[trade.code].append((trade.qty, cost_per_share))
            continue
        remaining = trade.qty
        proceeds_per_share = trade.cash_flow / trade.qty
        in_window = start_day <= trade.date <= end_day
        matches_filter = code_filter is None or trade.code in code_filter
        while remaining > 0 and lots[trade.code]:
            lot_qty, cost_per_share = lots[trade.code].popleft()
            matched = min(remaining, lot_qty)
            if in_window and matches_filter:
                realized += (proceeds_per_share - cost_per_share) * matched
            remaining -= matched
            if lot_qty > matched:
                lots[trade.code].appendleft((lot_qty - matched, cost_per_share))
    return realized
