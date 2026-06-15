"""Process-local automation safety state.

The kill switch intentionally lives outside the database so it can be toggled
without schema migrations. It is also seeded from `.env` on startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from backend.app.core.config import settings


@dataclass(slots=True)
class AutomationSafetyState:
    kill_switch_enabled: bool
    reason: str | None
    updated_at: datetime
    max_order_value: Decimal
    max_daily_loss_pct: Decimal


_state = AutomationSafetyState(
    kill_switch_enabled=settings.AUTOMATION_KILL_SWITCH,
    reason="Configured by AUTOMATION_KILL_SWITCH" if settings.AUTOMATION_KILL_SWITCH else None,
    updated_at=datetime.now().astimezone(),
    max_order_value=Decimal(str(settings.AUTOMATION_MAX_ORDER_VALUE)),
    max_daily_loss_pct=Decimal(str(settings.AUTOMATION_MAX_DAILY_LOSS_PCT)),
)


def get_safety_state() -> AutomationSafetyState:
    return _state


def set_kill_switch(enabled: bool, *, reason: str | None = None) -> AutomationSafetyState:
    _state.kill_switch_enabled = enabled
    _state.reason = reason
    _state.updated_at = datetime.now().astimezone()
    return _state


def is_kill_switch_enabled() -> bool:
    return _state.kill_switch_enabled


def assert_order_allowed(*, estimated_notional: Decimal, live_mode: bool) -> None:
    if not live_mode:
        return
    if _state.kill_switch_enabled:
        detail = f": {_state.reason}" if _state.reason else ""
        raise RuntimeError(f"Automation kill switch is enabled{detail}.")
    if estimated_notional > _state.max_order_value:
        raise RuntimeError(
            "Estimated order value exceeds AUTOMATION_MAX_ORDER_VALUE: "
            f"{estimated_notional} > {_state.max_order_value}"
        )
