<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# research/ — Quantitative Research Pipeline

## Purpose
Self-contained Python pipeline for factor-based equity research. Loads historical price/fundamental data (KRX, FinanceDataReader), computes multi-factor signals (value, quality, momentum, volume), runs vectorised backtests with walk-forward validation, and optimises strategy hyperparameters via Optuna. Output reports live in `reports/runs/`.

## Key Files

| File | Description |
|------|-------------|
| `scripts/run_backtest.py` | Main CLI entry — specify strategy YAML + universe |
| `scripts/optimize.py` | Optuna hyperparameter search |
| `scripts/download_universe.py` | Download KR universe price/financial data |
| `scripts/download_us_universe.py` | Download US universe data |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `backtest/` | Backtest engine, simulator, walk-forward, metrics |
| `data_ingestion/` | Loaders — pykrx, FinanceDataReader, financial statements, delisted |
| `factors/` | Factor computation — value, quality, momentum, volume, common utils |
| `strategies/` | Strategy definitions (YAML config + Python multi-factor) |
| `optimization/` | Grid search and Optuna wrappers |
| `universe/` | Universe construction — KOSPI200, KOSDAQ150, KOSPI All, KOSDAQ All |
| `notebooks/` | Exploratory Jupyter notebooks (not production code) |
| `reports/` | Generated run artifacts (gitignored) |
| `tests/` | Smoke tests for engine and US factors |

## For AI Agents

### Working In This Directory
- Do not modify without explicit user instruction.
- All backtests must guard against **look-ahead bias** (use only data available at signal date) and **survivorship bias** (include delisted stocks).
- A complete backtest run produces **5 output files**: metrics CSV, returns CSV, positions CSV, equity curve PNG, walk-forward summary.
- Walk-forward validation is mandatory — never accept in-sample-only results.

### Testing
```bash
pytest research/tests/ -v
ruff check research/
```

### Backtest Principles (from `backtest_principles` memory)
- Signal date T → execution at open T+1 (no same-bar fill)
- Delisted stocks included with `delisted_loader`
- Walk-forward windows: min 3 folds

## Dependencies

### Internal
- `shared/` — domain models, `research.db` SQLite

### External
- pandas, numpy, pykrx, FinanceDataReader, optuna, matplotlib

<!-- MANUAL: -->
