"""Programmatic Alembic upgrades for the two-branch (service/research) setup.

Lets the backend bring both DBs to their latest schema on startup, so a user
who never runs `alembic upgrade head` by hand doesn't hit a `no such table`
500 when new tables land (e.g. order_proposals). Idempotent — a DB already at
head is a no-op — and each branch is isolated so one failure never blocks the
other or the app.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _PROJECT_ROOT / "alembic.ini"

# Same names as the `--name` flag: `alembic --name service upgrade head`.
_BRANCHES = ("service", "research")


def upgrade_all() -> dict[str, str]:
    """Upgrade every branch to head. Returns {branch: 'ok'|'error'} per branch."""
    results: dict[str, str] = {}
    if not _ALEMBIC_INI.exists():
        logger.warning("db migrate: alembic.ini not found at %s — skipping", _ALEMBIC_INI)
        return {branch: "skipped" for branch in _BRANCHES}
    for branch in _BRANCHES:
        try:
            cfg = Config(str(_ALEMBIC_INI), ini_section=branch)
            command.upgrade(cfg, "head")
            results[branch] = "ok"
            logger.info("db migrate: %s upgraded to head", branch)
        except Exception:
            results[branch] = "error"
            logger.exception("db migrate: %s upgrade failed", branch)
    return results
