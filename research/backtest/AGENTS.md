<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# research/backtest/ — Backtesting Engine

## Purpose
Core backtest infrastructure for running historical strategy simulations. Implements a vectorised event-driven simulator with look-ahead bias prevention and mandatory walk-forward validation.

## Key Files

| File | Description |
|------|-------------|
| `engine.py` | Top-level backtest runner — wires data, strategy, simulator, and metrics together |
| `simulator.py` | Vectorised position/cash simulator — slippage, transaction costs, rebalance scheduler |
| `metrics.py` | Performance metric calculations — CAGR, Sharpe, MDD, Calmar, turnover, hit rate |
| `walk_forward.py` | Walk-forward validation — train/test split rolling window, out-of-sample aggregation |

## For AI Agents

### Bias Prevention (Inviolable)
- **Look-ahead bias**: all signals must use data aligned to T-1 or earlier at decision time
- **Survivorship bias**: include delisted stocks via `data_ingestion/delisted_loader.py`
- **Walk-forward is mandatory** — never report results from in-sample-only backtest

### 5-Output Run Format
Every backtest run must emit exactly these five outputs:
1. `equity_curve` — daily portfolio value series
2. `metrics_summary` — dict with CAGR/Sharpe/MDD/Calmar/turnover/hit_rate
3. `trade_log` — DataFrame of all trades (date, ticker, direction, qty, price, cost)
4. `position_snapshot` — final holdings
5. `walk_forward_results` — list of out-of-sample metric dicts per fold

### Running
```bash
python research/scripts/run_backtest.py --strategy multi_factor --start 2018-01-01 --end 2023-12-31
```

<!-- MANUAL: -->
