<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# shared/ — Shared Python Package

## Purpose
Python package (`shared`) imported by both `backend/` and `research/`. Provides the single source of truth for SQLAlchemy ORM models, Alembic migration management, domain value objects (mirroring Flutter `domain/entities/`), and cross-cutting utilities (logging, config helpers, time).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package init |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `db/` | SQLAlchemy models, async session factory, Alembic migrations (see `db/AGENTS.md`) |
| `domain/` | Pure Python domain value objects — alert, position, trade, watchlist, etc. |
| `utils/` | Logger, config helpers, time utilities |

## For AI Agents

### Working In This Directory
- Do not modify without explicit user instruction.
- Domain types here **must stay in sync** with Flutter `app/lib/domain/entities/` — if a field is added to the shared domain, the Flutter model needs a matching `fromJson` update.
- Database schema changes require an Alembic migration in `db/migrations/versions/`.
- Two migration branches: `service` (live app state) and `research` (backtest/factor data) — keep them independent.

### Testing
- Tests that depend on `shared` models live in `backend/tests/` and `research/tests/`.

## Dependencies

### External
- SQLAlchemy 2.x (async)
- Alembic
- pydantic

<!-- MANUAL: -->
