"""System health and automation status APIs."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.schemas.portfolio import ApiEnvelope
from backend.app.services.automation.safety import (
    AutomationSafetyState,
    get_safety_state,
    set_kill_switch,
)
from backend.app.services.kis.market_snapshot import (
    get_current_heatmap_snapshot,
    get_market_session,
)
from backend.app.services.llm.client import tokens_used_today
from shared.domain.account import AccountType
from shared.db.session import research_db_path

router = APIRouter(prefix="/api/system", tags=["system"])
automation_router = APIRouter(prefix="/api/automation", tags=["automation"])


class ComponentStatus(BaseModel):
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class SystemStatusResponse(BaseModel):
    checked_at: datetime
    market_session: str
    components: dict[str, ComponentStatus]


class AutomationStatusResponse(BaseModel):
    kill_switch_enabled: bool
    reason: str | None
    updated_at: datetime
    mock_modes: dict[str, bool]
    limits: dict[str, float]


class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: str | None = None


class DataQualityResponse(BaseModel):
    checked_at: datetime
    latest_price_date: str | None
    stocks_total: int
    prices_total: int
    financials_total: int
    missing_disclosed_at: int
    delisted_stocks: int
    factor_coverage: dict[str, int]


@router.get("/status", response_model=ApiEnvelope[SystemStatusResponse])
async def get_system_status(request: Request) -> ApiEnvelope[SystemStatusResponse]:
    snapshot = get_current_heatmap_snapshot()
    llm_used = tokens_used_today()
    components = {
        "service_db": _path_status(settings.service_db_path),
        "research_db": _path_status(settings.research_db_path),
        "kis_credentials": ComponentStatus(
            status="OK" if _any_kis_account_configured() else "WARN",
            details={
                account.value: settings.kis_account(account).is_active
                for account in AccountType
            },
        ),
        "kis_websocket": ComponentStatus(
            status="OK" if hasattr(request.app.state, "kis_ws_client") else "DISABLED",
            details={
                "autostart": settings.KIS_WS_AUTOSTART,
                "subscribed_codes": sorted(
                    getattr(getattr(request.app.state, "kis_ws_client", None), "subscribed_codes", set())
                ),
            },
        ),
        "market_snapshot": ComponentStatus(
            status="OK" if snapshot.items else ("WARN" if snapshot.errors else "EMPTY"),
            details={
                "autostart": settings.MARKET_SNAPSHOT_AUTOSTART,
                "updated_at": snapshot.updated_at.isoformat() if snapshot.updated_at else None,
                "source": snapshot.source,
                "items": len(snapshot.items),
                "errors": len(snapshot.errors),
            },
        ),
        "batch_scheduler": ComponentStatus(
            status="OK" if hasattr(request.app.state, "batch_scheduler") else "DISABLED",
            details={"autostart": settings.BATCH_SCHEDULER_AUTOSTART},
        ),
        "order_tracker": ComponentStatus(
            status="OK" if hasattr(request.app.state, "order_tracker") else "DISABLED",
            details={"autostart": settings.ORDER_TRACKER_AUTOSTART},
        ),
        "llm_budget": ComponentStatus(
            status="OK" if llm_used < settings.LLM_DAILY_TOKEN_BUDGET else "BLOCKED",
            details={
                "used_tokens_today": llm_used,
                "daily_budget": settings.LLM_DAILY_TOKEN_BUDGET,
                "remaining_tokens": max(settings.LLM_DAILY_TOKEN_BUDGET - llm_used, 0),
            },
        ),
        "automation_safety": _automation_component(get_safety_state()),
    }
    return ApiEnvelope(
        data=SystemStatusResponse(
            checked_at=datetime.now().astimezone(),
            market_session=get_market_session().value,
            components=components,
        ),
        error=None,
    )


@router.get("/data-quality", response_model=ApiEnvelope[DataQualityResponse])
async def get_data_quality() -> ApiEnvelope[DataQualityResponse]:
    return ApiEnvelope(data=await asyncio.to_thread(_data_quality), error=None)


@automation_router.get("/status", response_model=ApiEnvelope[AutomationStatusResponse])
async def get_automation_status() -> ApiEnvelope[AutomationStatusResponse]:
    return ApiEnvelope(data=_automation_response(get_safety_state()), error=None)


@automation_router.post("/kill-switch", response_model=ApiEnvelope[AutomationStatusResponse])
async def update_kill_switch(payload: KillSwitchRequest) -> ApiEnvelope[AutomationStatusResponse]:
    state = set_kill_switch(payload.enabled, reason=payload.reason)
    return ApiEnvelope(data=_automation_response(state), error=None)


def _path_status(path: Path) -> ComponentStatus:
    exists = path.exists()
    return ComponentStatus(
        status="OK" if exists else "WARN",
        details={
            "path": str(path),
            "exists": exists,
            "size_bytes": path.stat().st_size if exists else 0,
        },
    )


def _any_kis_account_configured() -> bool:
    return any(settings.kis_account(account).is_active for account in AccountType)


def _automation_response(state: AutomationSafetyState) -> AutomationStatusResponse:
    return AutomationStatusResponse(
        kill_switch_enabled=state.kill_switch_enabled,
        reason=state.reason,
        updated_at=state.updated_at,
        mock_modes={
            "rebalancer": settings.REBALANCER_IS_MOCK,
            "risk_manager": settings.RISK_MANAGER_IS_MOCK,
        },
        limits={
            "max_order_value": float(state.max_order_value),
            "max_daily_loss_pct": float(state.max_daily_loss_pct),
        },
    )


def _automation_component(state: AutomationSafetyState) -> ComponentStatus:
    return ComponentStatus(
        status="BLOCKED" if state.kill_switch_enabled else "OK",
        details=_automation_response(state).model_dump(mode="json"),
    )


def _data_quality() -> DataQualityResponse:
    with sqlite3.connect(research_db_path) as conn:
        latest_price_date = _scalar(conn, "SELECT MAX(date) FROM prices_daily")
        stocks_total = int(_scalar(conn, "SELECT COUNT(*) FROM stocks") or 0)
        prices_total = int(_scalar(conn, "SELECT COUNT(*) FROM prices_daily") or 0)
        financials_total = int(_scalar(conn, "SELECT COUNT(*) FROM financials") or 0)
        missing_disclosed_at = int(
            _scalar(conn, "SELECT COUNT(*) FROM financials WHERE disclosed_at IS NULL") or 0
        )
        delisted_stocks = int(
            _scalar(conn, "SELECT COUNT(*) FROM stocks WHERE is_delisted = 1") or 0
        )
        factor_coverage = {
            str(name): int(count)
            for name, count in conn.execute(
                """
                SELECT factor_name, COUNT(*)
                FROM factor_values
                WHERE value IS NOT NULL
                GROUP BY factor_name
                ORDER BY factor_name
                """
            ).fetchall()
        }
    return DataQualityResponse(
        checked_at=datetime.now().astimezone(),
        latest_price_date=str(latest_price_date) if latest_price_date else None,
        stocks_total=stocks_total,
        prices_total=prices_total,
        financials_total=financials_total,
        missing_disclosed_at=missing_disclosed_at,
        delisted_stocks=delisted_stocks,
        factor_coverage=factor_coverage,
    )


def _scalar(conn: sqlite3.Connection, sql: str) -> object:
    row = conn.execute(sql).fetchone()
    return row[0] if row else None
