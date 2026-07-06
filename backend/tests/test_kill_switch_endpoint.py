"""Integration test for the kill-switch endpoint (P1-6/P1-8).

Calls the endpoint function directly with the shared in-memory session fixture
(conftest.service_sessionmaker), verifying it both flips the in-memory safety
state and persists to the settings table.
"""

from __future__ import annotations

from backend.app.api.system import KillSwitchRequest, update_kill_switch
from backend.app.services.automation import safety
from backend.app.services.automation.store import load_kill_switch


async def test_kill_switch_endpoint_flips_and_persists(service_sessionmaker):
    safety.set_kill_switch(False)
    try:
        async with service_sessionmaker() as session:
            envelope = await update_kill_switch(
                KillSwitchRequest(enabled=True, reason="maintenance"),
                session,
            )
        assert envelope.error is None
        assert envelope.data.kill_switch_enabled is True
        assert safety.is_kill_switch_enabled() is True

        async with service_sessionmaker() as session:
            assert await load_kill_switch(session) == (True, "maintenance")
    finally:
        safety.set_kill_switch(False)


async def test_kill_switch_endpoint_disable_persists(service_sessionmaker):
    safety.set_kill_switch(True, reason="was on")
    try:
        async with service_sessionmaker() as session:
            await update_kill_switch(KillSwitchRequest(enabled=False), session)
        assert safety.is_kill_switch_enabled() is False
        async with service_sessionmaker() as session:
            assert await load_kill_switch(session) == (False, None)
    finally:
        safety.set_kill_switch(False)
