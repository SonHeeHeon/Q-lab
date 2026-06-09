"""
Package: research

The "experiment lab" — independent of `backend/` but shares `shared/`.

Two ways the engine is invoked:
  1. CLI scripts in research/scripts/ (download_universe, run_backtest, optimize)
  2. backend.app.api.backtest imports research.backtest.engine directly

Both write to the SAME `research/reports/runs/` folder and the SAME
`research/reports/leaderboard.csv` so the experiment record is unified.

Subpackages:
  - data_ingestion/  → fetch historical data into research.db
  - universe/        → universe definitions (KOSPI200, KOSPI all, KOSDAQ all)
  - factors/         → factor computations (Point-in-Time guarded)
  - strategies/      → YAML strategy definitions + composite logic
  - backtest/        → engine, simulator, metrics, walk_forward
  - optimization/    → grid_search, optuna_runner
  - reports/         → output (gitignored)
  - notebooks/       → Jupyter exploration (gitignored)
  - scripts/         → CLI entry points
"""
