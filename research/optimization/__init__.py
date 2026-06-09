"""
Package: research.optimization

Parameter-search wrappers around `research.backtest.engine.run_backtest`.

Files:
  - grid_search.py     → exhaustive grid over user-specified axes
  - optuna_runner.py   → Bayesian search (Optuna study persisted to disk)

Output:
    Each trial creates a normal run folder under `reports/runs/` and
    appends to `leaderboard.csv`. Optimization runs ALSO produce a
    summary CSV next to the study file showing the top-K trials.
"""
