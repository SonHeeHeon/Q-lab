<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/ — FastAPI Python Backend

## Purpose
FastAPI application serving the Flutter frontend and running scheduled background jobs. Aggregates data from KIS (Korea Investment Securities) and Toss Securities broker APIs, provides portfolio analytics, real-time quote streaming via WebSocket, LLM-powered trade journal analysis, and conditional alert / auto-trade execution.

## Key Files

| File | Description |
|------|-------------|
| `app/main.py` | FastAPI app factory — lifespan, routers, CORS, WebSocket mount |
| `app/core/config.py` | Pydantic Settings — reads `.env`, typed config object |
| `app/core/deps.py` | FastAPI dependency injectors (DB session, auth, broker factory) |
| `app/core/security.py` | Auth utilities |
| `scripts/run_daily_batch.py` | Entry point for cron-triggered daily batch |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `app/api/` | FastAPI route handlers (see `app/api/AGENTS.md`) |
| `app/services/` | Business logic — broker clients, LLM, alerts, batch (see `app/services/AGENTS.md`) |
| `app/schemas/` | Pydantic request/response models |
| `app/core/` | Config, deps, security |
| `app/ws/` | WebSocket quote hub |
| `tests/` | pytest test suite |
| `scripts/` | Dev/ops utility scripts |

## For AI Agents

### Working In This Directory
- Never modify without explicit user instruction — the Flutter developer has a rule against unsolicited backend edits.
- Never log `app_secret`, OAuth tokens, or any credential values.
- All broker I/O goes through `services/brokers/` (abstract base) → `services/kis/` or `services/toss/`.
- KIS account order validation: PAPER → REAL → ISA (never skip to REAL directly).
- The `shared/` package is a sibling on `PYTHONPATH` — import as `from shared.db.models import ...`.

### Testing
```bash
pytest backend/tests/ -v
ruff check backend/
```

### API Conventions
- Responses are wrapped: `{ "data": <payload>, "error": null }` on success; `{ "data": null, "error": { "code", "message", "details" } }` on failure.
- Monetary fields serialised as Pydantic `Decimal` (JSON strings like `"1380.50"`); Flutter's `safeDouble`/`safeDoubleOrNull` handles parsing.

## Dependencies

### Internal
- `shared/` — domain models, DB session, utils
- `data/service.db` — SQLite runtime database

### External
- FastAPI, SQLAlchemy 2.x async, httpx, pydantic-settings
- KIS OpenAPI, Toss Securities OpenAPI, OpenAI, Telegram Bot API

<!-- MANUAL: -->
