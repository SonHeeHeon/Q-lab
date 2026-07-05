<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# Q-Lab (StockCollect_Project)

## Purpose
Personal cross-platform stock app combining a Korean/US equity portfolio tracker, quantitative factor research engine, and LLM-assisted trade journal. The system integrates two live brokers (KIS/한국투자증권, Toss Securities) via real-time WebSocket and REST APIs, with a Flutter frontend and FastAPI backend.

## Repository Layout

| Directory | Purpose |
|-----------|---------|
| `app/` | Flutter 3.x cross-platform frontend (iOS/Android/Web) — package `qlab` |
| `backend/` | FastAPI Python backend — broker APIs, portfolio aggregation, LLM, alerts |
| `research/` | Quant research pipeline — factor models, backtesting, optimization |
| `shared/` | Python package shared by `backend/` and `research/` — DB models, domain types, utils |
| `data/` | Runtime SQLite databases, KIS/Toss token cache, manual seed CSVs |
| `docs/` | Toss OpenAPI spec, Architecture Decision Records |
| `logs/` | Backend rotating logs (auto-generated, not tracked) |

## Key Top-Level Files

| File | Description |
|------|-------------|
| `PROJECT_BLUEPRINT.md` | **Single Source of Truth** — full feature spec, API contracts, screen inventory |
| `pyproject.toml` | Python workspace — backend + research + shared package config |
| `docker-compose.yml` | Local development environment |
| `alembic.ini` | Alembic migration config (see `shared/db/migrations/`) |
| `.env` / `.env.example` | Environment variables — never commit `.env` |

## For AI Agents

### Critical Domain Rules
1. **Flutter-only writes**: Modify only `app/` Dart code unless explicitly asked. `backend/`, `research/`, `shared/` Python code requires explicit instruction.
2. **Security**: Never log KIS `app_secret`, Toss tokens, or any API keys.
3. **KIS account order**: Validation MUST follow PAPER → REAL → ISA sequence.
4. **Two-broker routing**: KIS handles KR equities; Toss handles US equities (AAPL etc.). `broker=TOSS` orders must never route through the KIS path.

### Testing
- Flutter: `cd app && flutter test`
- Backend: `pytest backend/tests/` (requires running DB)
- Research: `pytest research/tests/`
- Lint: `ruff check backend/ research/ shared/`

### Architecture
- State: Riverpod 2.x (Flutter), SQLAlchemy 2.x async (Python)
- HTTP: Dio 5.x (Flutter), httpx (Python)
- Real-time: WebSocket (`quotesProvider` in Flutter, `/ws/quotes` in backend)
- Routing: go_router 14.x
- Charts: fl_chart 0.69.x

## Dependencies

### External Services
- KIS OpenAPI (한국투자증권) — KR equities, portfolio
- Toss Securities OpenAPI — US equities, portfolio, FX rate
- OpenAI API — LLM trade journal analysis
- Telegram Bot API — alert notifications

<!-- MANUAL: -->
