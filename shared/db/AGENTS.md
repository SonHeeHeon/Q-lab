<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# shared/db/ — Database Models & Migrations

## Purpose
SQLAlchemy 2.x ORM models for the live service database (`data/service.db`) and research database (`data/research.db`), plus Alembic migration management. Two independent Alembic branches keep service and research schemas from interfering.

## Key Files

| File | Description |
|------|-------------|
| `models.py` | All SQLAlchemy ORM model classes — alerts, watchlist, portfolio snapshots, trades, journal, etc. |
| `session.py` | Async session factory (`AsyncSessionLocal`), `get_db` dependency |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `migrations/` | Alembic env + script template |
| `migrations/versions/service/` | Service schema migration history |
| `migrations/versions/research/` | Research schema migration history |

## For AI Agents

### Schema Changes Require Migrations
```bash
# Generate new migration
alembic -n service revision --autogenerate -m "describe_change"
alembic -n research revision --autogenerate -m "describe_change"

# Apply
alembic -n service upgrade head
alembic -n research upgrade head
```

### Two-Branch Rule
- `service` branch: live app state (alerts, watchlist, portfolio snapshots, orders, journal)
- `research` branch: factor data, backtest results, universe tables
- Never mix tables from both branches in a single migration

### Model Sync
ORM models must stay in sync with Flutter `app/lib/domain/entities/` — any field added here needs a corresponding `fromJson` update in the Flutter model.

<!-- MANUAL: -->
