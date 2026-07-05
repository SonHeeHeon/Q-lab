<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/services/ — Business Logic

## Purpose
All business logic, broker API clients, LLM integration, alert processing, and batch jobs. Route handlers in `api/` are thin wrappers that delegate to services here.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `kis/` | KIS (한국투자증권) REST client — OAuth, quotes, orders, portfolio (see `kis/AGENTS.md`) |
| `toss/` | Toss Securities REST client — OAuth, quotes, orders, portfolio, fx rate (see `toss/AGENTS.md`) |
| `llm/` | OpenAI LLM integration — trade journal analysis, principle extraction (see `llm/AGENTS.md`) |
| `alerts/` | Alert condition evaluation, trigger logic |
| `automation/` | Scheduled automation rules |
| `batch/` | Batch jobs — daily price sync, factor snapshot (see `batch/AGENTS.md`) |
| `brokers/` | Broker-agnostic abstraction layer |
| `market_data/` | Market snapshot, heatmap data aggregation |
| `notify/` | Telegram/push notification dispatch |

## For AI Agents

### Two-Broker Routing
| Broker | Used For | Client |
|--------|----------|--------|
| KIS | KR equities, KIS account portfolio/orders | `kis/rest_client.py` |
| TOSS | US equities, Toss account portfolio/orders, fx rate | `toss/rest_client.py` |

### Secret Safety
Never log `app_secret`, `access_token`, API keys, or Telegram bot tokens. Use `logger.info("token refreshed")` pattern.

### KIS Account Validation Order
PAPER (모의) → REAL → ISA — this order must be preserved in all KIS account resolution logic.

<!-- MANUAL: -->
