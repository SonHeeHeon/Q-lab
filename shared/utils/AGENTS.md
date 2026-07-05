<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# shared/utils/ — Cross-Cutting Utilities

## Purpose
Lightweight utility modules used by both `backend/` and `research/`. Covers structured logging, environment config helpers, and time/timezone utilities.

## Key Files

| File | Description |
|------|-------------|
| `logger.py` | Structured logger factory — `get_logger(__name__)` |
| `config.py` | Config helpers (env var reading, type coercion) |
| `time.py` | KST/UTC conversion, market-hours helpers, trading-day arithmetic |

## For AI Agents

### Logging Rule
Never log secrets through these utilities. Use `logger.info("token refreshed")` not `logger.info(f"token={secret}")`.

### Time Utilities
Korean market uses KST (UTC+9). Use `time.to_kst()` / `time.market_open_today()` rather than raw `datetime.now()` to avoid timezone bugs.

<!-- MANUAL: -->
