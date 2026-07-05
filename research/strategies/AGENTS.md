<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# research/strategies/ — Strategy Definitions

## Purpose
Concrete strategy implementations that consume factor scores and produce target portfolio weights. Strategies are stateless functions or classes consumed by `backtest/engine.py`.

## Key Files

| File | Description |
|------|-------------|
| `multi_factor.py` | Primary multi-factor long-only strategy — equal-weight top-N composite score |

## For AI Agents

### Strategy Interface
A strategy must implement:
```python
def generate_signals(self, factor_df: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    """Return target weights indexed by ticker. Weights must sum ≤ 1.0."""
```

### Constraints
- Long-only — no short positions
- Max single-position weight: 10% (enforced by `simulator.py`)
- Minimum ADTV liquidity filter applied before weighting

### Adding a New Strategy
1. Create `research/strategies/<name>.py`
2. Implement the signal interface above
3. Register in `research/scripts/run_backtest.py` strategy map
4. Run walk-forward validation; never report in-sample-only results

<!-- MANUAL: -->
