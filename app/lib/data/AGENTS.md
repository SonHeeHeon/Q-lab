<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/data/ — Data Layer (HTTP + WebSocket)

## Purpose
All network I/O. `api/` contains typed REST API clients (one per backend resource). `ws/` contains the live WebSocket quote client. `parse_utils.dart` provides null-safe JSON helpers used by all models.

## Key Files

| File | Description |
|------|-------------|
| `parse_utils.dart` | `safeDouble`, `safeDoubleOrNull`, `safeInt` — null-safe JSON number parsing from String or num |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `api/` | HTTP API clients — one file per backend resource group (see `api/AGENTS.md`) |
| `ws/` | WebSocket client for real-time quote ticks (see `ws/AGENTS.md`) |

## For AI Agents

### Always Use `parse_utils.dart` for Numbers
Backend sends Decimal fields as JSON strings. Never cast directly — use:
```dart
safeDouble(j['price'])        // returns 0.0 if null/absent
safeDoubleOrNull(j['price'])  // returns null if null/absent
safeInt(j['qty'])
```

### Adding a New API Client
1. Create `api/<resource>_api.dart` with models + `Provider<ResourceApi>`
2. Follow the `_EnvelopeResponse` unwrap pattern from `api_client.dart`
3. Add tests in `test/<resource>_api_test.dart`

<!-- MANUAL: -->
