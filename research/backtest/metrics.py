"""Performance metrics for backtest run reports."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date as Date
from math import sqrt

import pandas as pd
from pydantic import BaseModel

from research.backtest.simulator import SimulatedTrade


class Metrics(BaseModel):
    cagr: float
    mdd: float
    sharpe: float
    sortino: float
    win_rate: float
    avg_holding_days: float
    turnover: float
    n_trades: int


def compute_metrics(
    equity_curve: list[tuple[Date, float]],
    trades: list[SimulatedTrade],
    *,
    risk_free_rate: float = 0.02,
) -> Metrics:
    """Compute standard performance metrics from NAV and simulated trades."""

    if not equity_curve:
        return Metrics(
            cagr=0.0,
            mdd=0.0,
            sharpe=0.0,
            sortino=0.0,
            win_rate=0.0,
            avg_holding_days=0.0,
            turnover=0.0,
            n_trades=len(trades),
        )

    frame = pd.DataFrame(equity_curve, columns=["date", "nav"])
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date")
    nav = frame["nav"].astype(float)
    returns = nav.pct_change().dropna()

    first_nav = float(nav.iloc[0])
    last_nav = float(nav.iloc[-1])
    days = max((frame["date"].iloc[-1] - frame["date"].iloc[0]).days, 1)
    cagr = (last_nav / first_nav) ** (365.0 / days) - 1.0 if first_nav > 0 else 0.0

    running_peak = nav.cummax()
    drawdowns = nav / running_peak - 1.0
    mdd = float(drawdowns.min()) if not drawdowns.empty else 0.0

    rf_daily = (1.0 + risk_free_rate) ** (1.0 / 252.0) - 1.0
    excess = returns - rf_daily
    sharpe = _annualized_ratio(excess)
    downside = excess[excess < 0]
    sortino = _annualized_ratio(excess, denominator=downside.std(ddof=1))

    win_rate, avg_holding_days = _round_trip_stats(trades)
    turnover = _annualized_turnover(trades, nav.mean(), days)

    return Metrics(
        cagr=float(cagr),
        mdd=mdd,
        sharpe=sharpe,
        sortino=sortino,
        win_rate=win_rate,
        avg_holding_days=avg_holding_days,
        turnover=turnover,
        n_trades=len(trades),
    )


def _annualized_ratio(
    series: pd.Series,
    *,
    denominator: float | None = None,
) -> float:
    if series.empty:
        return 0.0
    std = float(series.std(ddof=1) if denominator is None else denominator)
    if std == 0.0 or pd.isna(std):
        return 0.0
    return float(series.mean() / std * sqrt(252.0))


def _round_trip_stats(trades: list[SimulatedTrade]) -> tuple[float, float]:
    lots: dict[str, deque[tuple[int, float, Date]]] = defaultdict(deque)
    closed_trades = 0
    winning_trades = 0
    holding_days: list[int] = []

    for trade in sorted(trades, key=lambda item: item.date):
        if trade.qty <= 0:
            continue

        if trade.side == "BUY":
            cost_per_share = -trade.cash_flow / trade.qty
            lots[trade.code].append((trade.qty, cost_per_share, trade.date))
            continue

        remaining = trade.qty
        proceeds_per_share = trade.cash_flow / trade.qty
        pnl = 0.0

        while remaining > 0 and lots[trade.code]:
            lot_qty, cost_per_share, buy_date = lots[trade.code].popleft()
            matched_qty = min(remaining, lot_qty)
            pnl += (proceeds_per_share - cost_per_share) * matched_qty
            holding_days.append(max((trade.date - buy_date).days, 0))
            remaining -= matched_qty

            if lot_qty > matched_qty:
                lots[trade.code].appendleft(
                    (lot_qty - matched_qty, cost_per_share, buy_date)
                )

        closed_trades += 1
        if pnl > 0:
            winning_trades += 1

    win_rate = winning_trades / closed_trades if closed_trades else 0.0
    avg_holding = sum(holding_days) / len(holding_days) if holding_days else 0.0
    return float(win_rate), float(avg_holding)


def _annualized_turnover(
    trades: list[SimulatedTrade],
    average_nav: float,
    days: int,
) -> float:
    if average_nav <= 0 or days <= 0:
        return 0.0
    total_notional = sum(trade.notional for trade in trades)
    years = days / 365.0
    return float((total_notional / average_nav) / years)
