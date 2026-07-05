<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# research/universe/ — Stock Universe Filters

## Purpose
Defines investable universe sets used by strategies. Each module exports a function that returns a list of tickers valid for a given date, including historically delisted stocks to prevent survivorship bias.

## Key Files

| File | Description |
|------|-------------|
| `kospi200.py` | KOSPI 200 index universe (point-in-time reconstruction) |
| `kospi_all.py` | Full KOSPI market universe with liquidity filter |
| `kosdaq150.py` | KOSDAQ 150 index universe |
| `kosdaq_all.py` | Full KOSDAQ market universe with liquidity filter |

## For AI Agents

### Point-in-Time Integrity
Universe membership must be reconstructed as of each rebalance date — use historical constituent lists, not today's index composition. `kospi200.py` loads constituent history from the cached KRX file.

### Survivorship Bias
All universe modules include stocks that were delisted during the backtest period. The `data_ingestion/delisted_loader.py` must be called when building training sets.

### Downloading Universe Data
```bash
python research/scripts/download_universe.py      # KR markets
python research/scripts/download_us_universe.py   # US markets
```

<!-- MANUAL: -->
