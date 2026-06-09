"""
Module: research.optimization.grid_search

Role:
    Exhaustive grid search over a user-specified parameter space.

CLI form (via research.scripts.optimize):
    --param per_weight=-1.5,-1.0,-0.5  --param top_n=10,20,30

API:
    def grid_search(base_strategy, axes: dict[str, list]) -> list[RunResult]

Behavior:
    - Cartesian product of all axis values.
    - One backtest per combination.
    - Each combination's params are merged into a fresh StrategyDefinition.

Connected modules:
    - research.backtest.engine.run_backtest
    - research.scripts.optimize (CLI entry)
"""
