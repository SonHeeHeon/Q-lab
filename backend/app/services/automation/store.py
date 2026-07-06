"""Durable persistence for the automation kill switch.

``AutomationSafetyState`` (safety.py) is process-local and fast, but a runtime
kill-switch toggle was lost on restart. We mirror the kill switch to the
``settings`` table so it survives a backend restart; startup re-seeds the
in-memory state from here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Setting

_KEY_ENABLED = "automation.kill_switch"
_KEY_REASON = "automation.kill_switch_reason"


async def save_kill_switch(
    session: AsyncSession,
    *,
    enabled: bool,
    reason: str | None,
) -> None:
    """Persist the kill-switch state to the settings table."""
    await _upsert(session, _KEY_ENABLED, "true" if enabled else "false")
    await _upsert(session, _KEY_REASON, reason or "")
    await session.commit()


async def load_kill_switch(session: AsyncSession) -> tuple[bool, str | None] | None:
    """Return ``(enabled, reason)`` if persisted, else None (never set)."""
    result = await session.execute(
        select(Setting).where(Setting.key.in_([_KEY_ENABLED, _KEY_REASON]))
    )
    rows = {row.key: row.value for row in result.scalars()}
    if _KEY_ENABLED not in rows:
        return None
    enabled = rows[_KEY_ENABLED].strip().lower() == "true"
    reason = rows.get(_KEY_REASON) or None
    return enabled, reason


async def _upsert(session: AsyncSession, key: str, value: str) -> None:
    existing = await session.get(Setting, key)
    if existing is None:
        session.add(Setting(key=key, value=value))
    else:
        existing.value = value
