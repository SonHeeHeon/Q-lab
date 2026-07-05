<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/ — Flutter Frontend (qlab)

## Purpose
Flutter 3.x cross-platform application (iOS / Android / Web). Implements all 10 user-facing screens: Home, Portfolio, Stock Search/Detail, Watchlist, Trade Journal, Alerts & Auto-Trade, Heatmap, Quant, Principles, Settings. Package name: `qlab`.

## Key Files

| File | Description |
|------|-------------|
| `pubspec.yaml` | Dependencies — Riverpod 2.x, Dio 5.x, go_router 14.x, fl_chart 0.69.x, intl, shared_preferences |
| `analysis_options.yaml` | Linter rules (flutter_lints 4.x) |
| `lib/main.dart` | App entry point — ProviderScope, GoRouter, theme setup |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `lib/` | All Dart source (see `lib/AGENTS.md`) |
| `test/` | Unit + widget tests |
| `android/` | Android platform host |

## For AI Agents

### Working In This Directory
- **Only modify files under `app/`** — the backend/research Python code is off-limits unless explicitly requested.
- Run `flutter pub get` after changing `pubspec.yaml`.
- Use `flutter analyze` to catch type errors before claiming completion.
- All monetary values use `app/lib/shared/format/money.dart` helpers (`krwFmt`, `usdFmt`, `formatNative`, `krwFromNative`).

### Testing
```bash
cd app
flutter test          # run all tests
flutter analyze       # static analysis — must have 0 new errors
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000
```

### Common Patterns
- State: `ConsumerWidget` / `ConsumerStatefulWidget` (Riverpod)
- HTTP: all API calls go through `data/api/*_api.dart` — never instantiate Dio directly
- Navigation: `context.go('/path')` or `context.push('/path')` (go_router)
- Error display: `.when(data:, loading:, error:)` on `AsyncValue`
- Two-broker routing: `BrokerType.KIS` for KR, `BrokerType.TOSS` for US

## Dependencies

### Internal
- See `shared/` Python package for domain model reference (mirrored in `lib/domain/entities/`)

### External (key)
- `flutter_riverpod ^2.5.1` — state management
- `go_router ^14.2.7` — declarative routing
- `dio ^5.7.0` — HTTP client
- `fl_chart ^0.69.0` — price charts
- `web_socket_channel ^3.0.1` — live quotes WebSocket

<!-- MANUAL: -->
