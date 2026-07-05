<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/core/ — FastAPI Core Wiring

## Purpose
App-wide config (pydantic-settings), dependency injection helpers, and security middleware. Not business logic — wires the framework layer together.

## Key Files

| File | Description |
|------|-------------|
| `config.py` | `Settings` pydantic-settings model — reads env vars (KIS credentials, DB path, Toss keys, Telegram token, OpenAI key) |
| `deps.py` | FastAPI dependency injectors — `get_db`, `get_current_user`, `get_settings` |
| `security.py` | Request authentication — API key or JWT validation |

## For AI Agents

### Secret Loading
All secrets are loaded from env vars via `Settings` in `config.py`. Never hardcode credentials. Never log `Settings` model repr (it will expose secrets).

### Dependency Injection
Use `Depends(get_db)` for DB sessions, `Depends(get_settings)` for config. Do not instantiate `Settings()` directly inside route handlers.

<!-- MANUAL: -->
