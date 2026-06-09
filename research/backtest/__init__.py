"""
Package: research.backtest

Backtest engine.

Files:
  - engine.py        → main loop: rebalance, fill, mark-to-market
  - simulator.py     → fee + slippage model (KRX-specific)
  - metrics.py       → CAGR, MDD, Sharpe, Sortino, win-rate, turnover
  - walk_forward.py  → rolling-window validation (overfit guard)

Three cardinal rules (PROJECT_BLUEPRINT.md §11):
  1. Point-in-time data only.
  2. Survivorship-free universe (delisted stocks INCLUDED).
  3. Realistic execution (KRX fees + slippage).
"""
