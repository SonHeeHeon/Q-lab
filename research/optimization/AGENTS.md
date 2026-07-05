<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# research/optimization/ — Hyperparameter Optimization

## Purpose
Tunes strategy hyperparameters (factor weights, lookback windows, top-N, rebalance frequency) using grid search or Bayesian optimization (Optuna). Always optimises on training folds only — validation on separate out-of-sample folds.

## Key Files

| File | Description |
|------|-------------|
| `grid_search.py` | Exhaustive grid search over discrete parameter space |
| `optuna_runner.py` | Optuna TPE sampler for continuous/mixed parameter spaces |

## For AI Agents

### Overfitting Guard
Optimization is run on training folds only. Never select the best parameters by looking at the test fold — the test fold result is reported after parameter selection is frozen.

### Running Optimization
```bash
python research/scripts/optimize.py --strategy multi_factor --n_trials 100
```

### Output
Results are saved to `research/reports/` as JSON. The `backend/app/api/backtest.py` reads these reports to serve the Flutter quant screen.

<!-- MANUAL: -->
