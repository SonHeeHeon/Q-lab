"""Backtest REST API backed by the research engine."""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.app.schemas.portfolio import ApiEnvelope, ApiError
from backend.app.services.batch.daily_analysis import (
    PRIVATE_STRATEGY_DIR,
    STRATEGY_DIR,
    load_strategy,
)
from research.backtest.engine import RunResult, run_backtest
from research.backtest.portfolio import (
    PortfolioResult,
    RebalanceFreq,
    optimize_sleeve_weights,
    optimize_sleeve_weights_oos,
    run_portfolio_backtest,
)
from research.backtest.tax_kr import TaxModel, default_tax_model_for_universe
from research.scripts.run_backtest import (
    LEADERBOARD_PATH,
    PORTFOLIO_LEADERBOARD_PATH,
    PORTFOLIOS_ROOT,
    RUNS_ROOT,
    write_portfolio_report,
    write_report,
)
from shared.domain.strategy import StrategyDefinition

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

# Optuna trial counts for on-demand portfolio weight search — kept modest
# since these run synchronously (in a thread) within one HTTP request.
PORTFOLIO_INSAMPLE_TRIALS = 100
PORTFOLIO_OOS_TRIALS = 50


class PortfolioSleeveRequest(BaseModel):
    strategy_name: str
    weight: float


class RunPortfolioRequest(BaseModel):
    sleeves: list[PortfolioSleeveRequest]
    rebalance: RebalanceFreq = "QUARTERLY"
    optimize: bool = False
    oos: bool = False


@router.post("/run", response_model=ApiEnvelope[dict[str, Any]])
async def run_backtest_api(
    strategy: StrategyDefinition, after_tax: bool = False
) -> ApiEnvelope[dict[str, Any]]:
    """Run a backtest synchronously and persist the standard report artifacts.

    ``after_tax`` is a query param (the body is the bare StrategyDefinition).
    Unsupported universes (US) never 500 — they fall back to a pre-tax run
    and surface a warning in the response instead.
    """

    tax_model: TaxModel | None = None
    warnings: list[str] = []
    applied_after_tax = False
    if after_tax:
        tax_model = default_tax_model_for_universe(strategy.universe)
        if tax_model is None:
            warnings.append(
                f"after_tax 미지원 유니버스({strategy.universe}) — 세전으로 실행"
            )
        else:
            applied_after_tax = True

    result, run_dir = await asyncio.to_thread(
        _run_and_write_report,
        strategy,
        tax_model=tax_model,
        run_options={"after_tax": applied_after_tax},
    )
    data: dict[str, Any] = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "result": result.model_dump(mode="json"),
        "after_tax": applied_after_tax,
    }
    if warnings:
        data["warnings"] = warnings
    return ApiEnvelope(data=data, error=None)


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


@router.post("/run-portfolio", response_model=ApiEnvelope[dict[str, Any]])
async def run_portfolio_backtest_api(
    request: RunPortfolioRequest, after_tax: bool = False
) -> ApiEnvelope[dict[str, Any]] | JSONResponse:
    """Blend N strategy sleeves at fixed weights and persist the report.

    ``optimize=True`` additionally runs an in-sample Optuna weight search
    (``optimize_sleeve_weights``); ``oos=True`` (only meaningful alongside
    ``optimize``) also runs the walk-forward out-of-sample search
    (``optimize_sleeve_weights_oos``). Both only ever inform the response's
    ``optimal`` field — the persisted/returned portfolio result itself always
    uses the caller-supplied ``sleeves`` weights.
    """
    if not request.sleeves:
        return _portfolio_bad_request("EMPTY_SLEEVES", "sleeves must not be empty")

    resolved: list[tuple[StrategyDefinition, float]] = []
    for sleeve in request.sleeves:
        try:
            strategy = load_strategy(sleeve.strategy_name)
        except FileNotFoundError:
            return _portfolio_bad_request(
                "UNKNOWN_STRATEGY", f"Strategy not found: {sleeve.strategy_name}"
            )
        resolved.append((strategy, sleeve.weight))

    result, optimal = await asyncio.to_thread(
        _run_portfolio_and_optimize, resolved, request, after_tax
    )

    run_dir = write_portfolio_report(
        result, weights_meta={"after_tax": after_tax, **optimal}
    )

    data: dict[str, Any] = {
        "portfolio_id": run_dir.name,
        "rebalance": result.rebalance,
        "after_tax": after_tax,
        "weights": result.weights,
        "combined_metrics": result.combined_metrics.model_dump(mode="json"),
        "sleeves": [
            {
                "strategy_name": sleeve["strategy_name"],
                "weight": sleeve["weight"],
                "metrics": sleeve["metrics"].model_dump(mode="json"),
            }
            for sleeve in result.sleeves
        ],
        "optimal": optimal,
    }
    return ApiEnvelope(data=data, error=None)


@router.get("/portfolios", response_model=ApiEnvelope[list[dict[str, Any]]])
async def list_portfolio_backtests() -> ApiEnvelope[list[dict[str, Any]]]:
    """Return the accumulated portfolio-backtest leaderboard."""

    if not PORTFOLIO_LEADERBOARD_PATH.exists():
        return ApiEnvelope(data=[], error=None)

    with PORTFOLIO_LEADERBOARD_PATH.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    return ApiEnvelope(data=rows, error=None)


@router.get("/portfolios/{portfolio_id}", response_model=ApiEnvelope[dict[str, Any]])
async def get_portfolio_backtest(portfolio_id: str) -> ApiEnvelope[dict[str, Any]]:
    """Return the persisted metrics/weights/sleeves/curve for a portfolio run."""

    run_dir = _safe_portfolio_dir(portfolio_id)
    combined_metrics_path = run_dir / "combined_metrics.json"
    weights_path = run_dir / "weights.json"
    sleeves_path = run_dir / "sleeves.json"
    curve_path = run_dir / "blended_equity_curve.csv"

    if not run_dir.exists() or not combined_metrics_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Portfolio run not found: {portfolio_id}"
        )

    with combined_metrics_path.open("r", encoding="utf-8") as file:
        combined_metrics = json.load(file)
    with weights_path.open("r", encoding="utf-8") as file:
        weights = json.load(file)
    with sleeves_path.open("r", encoding="utf-8") as file:
        sleeves = json.load(file)

    blended_curve: list[dict[str, Any]] = []
    if curve_path.exists():
        with curve_path.open("r", encoding="utf-8", newline="") as file:
            blended_curve = list(csv.DictReader(file))

    return ApiEnvelope(
        data={
            "portfolio_id": portfolio_id,
            "combined_metrics": combined_metrics,
            "weights": weights,
            "sleeves": sleeves,
            "blended_curve": blended_curve,
        },
        error=None,
    )


def _run_portfolio_and_optimize(
    resolved: list[tuple[StrategyDefinition, float]],
    request: RunPortfolioRequest,
    after_tax: bool,
) -> tuple[PortfolioResult, dict[str, Any]]:
    """Blend the sleeves and, if requested, search for optimal weights.

    Runs synchronously — the caller is expected to dispatch this through
    ``asyncio.to_thread`` since both the blend and the Optuna searches are
    blocking CPU/IO work.
    """
    result = run_portfolio_backtest(
        resolved, rebalance=request.rebalance, after_tax=after_tax
    )

    optimal: dict[str, Any] = {}
    if request.optimize:
        strategies_only = [strategy for strategy, _ in resolved]
        optimal["insample"] = optimize_sleeve_weights(
            strategies_only,
            rebalance=request.rebalance,
            trials=PORTFOLIO_INSAMPLE_TRIALS,
            after_tax=after_tax,
        )
        if request.oos:
            optimal["oos"] = optimize_sleeve_weights_oos(
                strategies_only,
                rebalance=request.rebalance,
                trials=PORTFOLIO_OOS_TRIALS,
                after_tax=after_tax,
            )
    return result, optimal


def _portfolio_bad_request(code: str, message: str) -> JSONResponse:
    envelope = ApiEnvelope(data=None, error=ApiError(code=code, message=message, details=None))
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=envelope.model_dump(mode="json"),
    )


def _safe_portfolio_dir(portfolio_id: str) -> Path:
    if "/" in portfolio_id or "\\" in portfolio_id or portfolio_id in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid portfolio_id")
    run_dir = (PORTFOLIOS_ROOT / portfolio_id).resolve()
    portfolios_root = PORTFOLIOS_ROOT.resolve()
    if portfolios_root not in run_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid portfolio_id")
    return run_dir


def _run_and_write_report(
    strategy: StrategyDefinition,
    *,
    tax_model: TaxModel | None = None,
    run_options: dict[str, Any] | None = None,
) -> tuple[RunResult, Path]:
    result = run_backtest(strategy, tax_model=tax_model)
    run_dir = write_report(result, strategy, tag=strategy.name, run_options=run_options)
    return result, run_dir


def _safe_run_dir(run_id: str) -> Path:
    if "/" in run_id or "\\" in run_id or run_id in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid run_id")
    run_dir = (RUNS_ROOT / run_id).resolve()
    runs_root = RUNS_ROOT.resolve()
    if runs_root not in run_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid run_id")
    return run_dir
