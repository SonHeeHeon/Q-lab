"""Backtest REST API backed by the research engine."""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.batch.daily_analysis import (
    PRIVATE_STRATEGY_DIR,
    STRATEGY_DIR,
    load_strategy,
)
from research.backtest.engine import RunResult, run_backtest
from research.scripts.run_backtest import LEADERBOARD_PATH, RUNS_ROOT, write_report
from shared.domain.strategy import StrategyDefinition

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.post("/run", response_model=ApiEnvelope[dict[str, Any]])
async def run_backtest_api(strategy: StrategyDefinition) -> ApiEnvelope[dict[str, Any]]:
    """Run a backtest synchronously and persist the standard report artifacts."""

    result, run_dir = await asyncio.to_thread(_run_and_write_report, strategy)
    return ApiEnvelope(
        data={
            "run_id": run_dir.name,
            "run_dir": str(run_dir),
            "result": result.model_dump(mode="json"),
        },
        error=None,
    )


@router.get("/runs", response_model=ApiEnvelope[list[dict[str, Any]]])
async def list_backtest_runs() -> ApiEnvelope[list[dict[str, Any]]]:
    """Return the accumulated backtest leaderboard."""

    if not LEADERBOARD_PATH.exists():
        return ApiEnvelope(data=[], error=None)

    with LEADERBOARD_PATH.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    return ApiEnvelope(data=rows, error=None)


@router.get("/runs/{run_id}", response_model=ApiEnvelope[dict[str, Any]])
async def get_backtest_run(run_id: str) -> ApiEnvelope[dict[str, Any]]:
    """Return metrics and params for a saved backtest run."""

    run_dir = _safe_run_dir(run_id)
    metrics_path = run_dir / "metrics.json"
    params_path = run_dir / "params.yaml"

    if not run_dir.exists() or not metrics_path.exists() or not params_path.exists():
        raise HTTPException(status_code=404, detail=f"Backtest run not found: {run_id}")

    with metrics_path.open("r", encoding="utf-8") as file:
        metrics = json.load(file)
    with params_path.open("r", encoding="utf-8") as file:
        params = yaml.safe_load(file) or {}

    # Per-trade log with logic-based reasons (trades.json written by write_report;
    # older runs may lack it — return an empty list rather than 404).
    trades: list[dict[str, Any]] = []
    trades_path = run_dir / "trades.json"
    if trades_path.exists():
        with trades_path.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
        if isinstance(loaded, list):
            trades = loaded

    return ApiEnvelope(
        data={
            "run_id": run_id,
            "metrics": metrics,
            "params": params,
            "trades": trades,
        },
        error=None,
    )


@router.get("/strategies", response_model=ApiEnvelope[list[dict[str, Any]]])
async def list_strategies() -> ApiEnvelope[list[dict[str, Any]]]:
    """List usable strategy presets (private/ gitignored dir wins over public).

    Globs the filesystem at runtime because personal tuned strategies live in
    research/strategies/private/ which is never committed. Returns lightweight
    metadata so the builder can offer a preset dropdown.
    """
    seen: dict[str, dict[str, Any]] = {}
    # Private first so a private preset shadows a same-named public one.
    for directory, is_private in ((PRIVATE_STRATEGY_DIR, True), (STRATEGY_DIR, False)):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            name = path.stem
            if name in seen:
                continue
            try:
                with path.open("r", encoding="utf-8") as file:
                    payload = yaml.safe_load(file) or {}
            except (OSError, yaml.YAMLError):
                continue
            groups = payload.get("groups")
            seen[name] = {
                "name": payload.get("name", name),
                "description": payload.get("description", ""),
                "universe": payload.get("universe"),
                "rebalance_freq": payload.get("rebalance_freq"),
                "top_n": payload.get("top_n"),
                "is_private": is_private,
                # groups-mode presets can't be edited in the flat factor UI —
                # the client uses this to switch to read-only "use as-is" mode.
                "is_grouped": bool(groups),
            }
    return ApiEnvelope(data=list(seen.values()), error=None)


@router.get("/strategies/{name}", response_model=ApiEnvelope[dict[str, Any]])
async def get_strategy(name: str) -> ApiEnvelope[dict[str, Any]]:
    """Return a full strategy preset (incl. groups) for loading into the builder."""
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid strategy name")
    try:
        strategy = load_strategy(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Strategy not found: {name}")
    return ApiEnvelope(data=strategy.model_dump(mode="json"), error=None)


def _run_and_write_report(strategy: StrategyDefinition) -> tuple[RunResult, Path]:
    result = run_backtest(strategy)
    run_dir = write_report(result, strategy, tag=strategy.name)
    return result, run_dir


def _safe_run_dir(run_id: str) -> Path:
    if "/" in run_id or "\\" in run_id or run_id in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid run_id")
    run_dir = (RUNS_ROOT / run_id).resolve()
    runs_root = RUNS_ROOT.resolve()
    if runs_root not in run_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid run_id")
    return run_dir
