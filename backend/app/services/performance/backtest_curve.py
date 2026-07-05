"""Load persisted backtest equity curves from ``research/reports/runs/*``.

The backtest CLI writes each run to ``research/reports/runs/<run_id>/`` where
``run_id = "<YYYYMMDD_HHMMSS>_<slug>"`` and ``slug = _slug(strategy.name)``
(see ``research/scripts/run_backtest.py``). No existing endpoint serves the
``equity_curve.csv``, so the performance API reads it directly.
"""

from __future__ import annotations

import csv
import re
from datetime import date as Date
from pathlib import Path

from research.scripts.run_backtest import RUNS_ROOT, _slug

_RUN_ID_PREFIX = re.compile(r"^\d{8}_\d{6}_")


def list_run_dirs_for_strategy(strategy_name: str) -> list[Path]:
    """Run directories for ``strategy_name``, newest first (lexical == chrono)."""
    if not RUNS_ROOT.exists():
        return []
    slug = _slug(strategy_name)
    pattern = re.compile(r"^\d{8}_\d{6}_" + re.escape(slug) + r"$")
    matches = [
        path
        for path in RUNS_ROOT.iterdir()
        if path.is_dir() and pattern.match(path.name)
    ]
    return sorted(matches, key=lambda path: path.name, reverse=True)


def load_latest_backtest_curve(strategy_name: str) -> list[tuple[Date, float]]:
    """Equity curve of the most recent backtest run for ``strategy_name``.

    Returns an empty list when no run exists (the caller renders an empty state).
    """
    for run_dir in list_run_dirs_for_strategy(strategy_name):
        curve = read_equity_curve(run_dir / "equity_curve.csv")
        if curve:
            return curve
    return []


def read_equity_curve(path: Path) -> list[tuple[Date, float]]:
    """Parse an ``equity_curve.csv`` (columns ``date,nav``); skip bad rows."""
    if not path.exists():
        return []
    curve: list[tuple[Date, float]] = []
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                curve.append(
                    (Date.fromisoformat(row["date"]), float(row["nav"]))
                )
            except (KeyError, ValueError, TypeError):
                continue
    return curve
