"""
Package: research.scripts

CLI entry points. Each script is intended to be run with `uv run`:

  $ uv run python research/scripts/download_universe.py --universe KOSPI200 --years 10
  $ uv run python research/scripts/run_backtest.py --strategy research/strategies/value_v1.yaml
  $ uv run python research/scripts/optimize.py --strategy ... --param per_weight=-1.5,-1.0,-0.5
"""
