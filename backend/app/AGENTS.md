<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/ — FastAPI Application Package

## Purpose
The FastAPI application package. `main.py` wires together API routers, WebSocket mount, lifespan (DB init, scheduler start), and CORS. Sub-packages provide the full request → response → service → broker pipeline.

## Key Files

| File | Description |
|------|-------------|
| `main.py` | App factory: lifespan, include_router for all API modules, WebSocket mount, CORS |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `api/` | Route handlers — one file per resource (see `api/AGENTS.md`) |
| `services/` | Business logic — broker clients, LLM, alerts, batch jobs (see `services/AGENTS.md`) |
| `schemas/` | Pydantic request/response models — `portfolio.py` is the largest |
| `core/` | Config (pydantic-settings), dependency injectors, security |
| `ws/` | WebSocket quote hub — broadcasts real-time ticks to Flutter clients |

## For AI Agents

### Response Envelope
All REST responses use:
```python
{ "data": <payload_or_null>, "error": null | { "code", "message", "details" } }
```
Flutter's `_EnvelopeInterceptor` in `api_client.dart` unwraps this automatically.

### Monetary Serialisation
Pydantic `Decimal` fields serialise as JSON strings (e.g., `"1380.50"`). Flutter uses `safeDouble` / `safeDoubleOrNull` to parse them.

### Adding a New API Endpoint
1. Add route handler in `api/<resource>.py`
2. Add Pydantic schemas in `schemas/<resource>.py` (or `schemas/portfolio.py` for portfolio-adjacent)
3. Register router in `main.py`

<!-- MANUAL: -->
