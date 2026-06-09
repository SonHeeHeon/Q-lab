"""
Module: research.scripts.optimize

Role:
    CLI: parameter search around a base strategy.

Usage (grid):
    $ uv run python research/scripts/optimize.py \
          --strategy research/strategies/value_v1.yaml \
          --grid \
          --param per_weight=-1.5,-1.0,-0.5 \
          --param top_n=10,20,30

Usage (Optuna):
    $ uv run python research/scripts/optimize.py \
          --strategy research/strategies/value_v1.yaml \
          --optuna --trials 100 --objective sharpe

Output:
    Every trial becomes a normal run under reports/runs/. The script
    also writes an optimization summary CSV showing top-K results.

Connected modules:
    - research.optimization.grid_search, optuna_runner
    - shared.domain.strategy.StrategyDefinition
"""
