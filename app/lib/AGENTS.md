<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/ — Dart Source Root

## Purpose
All Dart source code for the `qlab` Flutter app. Follows a layered clean-architecture layout: `core` (config/routing/theme) → `data` (API clients, WebSocket) → `domain` (pure entities) → `presentation` (screens + controllers) → `shared` (reusable widgets and format utils).

## Key Files

| File | Description |
|------|-------------|
| `main.dart` | App entry — `ProviderScope`, `MaterialApp.router`, theme, GoRouter wiring |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core/` | App-wide config, env, routing (go_router), theme, account preferences (see `core/AGENTS.md`) |
| `data/` | HTTP API clients and WebSocket client (see `data/AGENTS.md`) |
| `domain/` | Pure Dart entities with no Flutter dependency (see `domain/AGENTS.md`) |
| `presentation/` | Feature screens + Riverpod controllers (see `presentation/AGENTS.md`) |
| `shared/` | Format utils (`money.dart`) and reusable widgets |

## For AI Agents

### Dependency Flow (enforce, never reverse)
```
presentation → domain, data, shared
data         → domain
domain       → (nothing internal)
shared       → (nothing internal)
core         → (nothing internal)
```

### Key Providers (global singletons)
| Provider | File | Purpose |
|----------|------|---------|
| `dioProvider` | `data/api/api_client.dart` | Shared Dio HTTP client |
| `quotesProvider` | `data/ws/quotes_ws_client.dart` | Live WebSocket quote stream |
| `routerProvider` | `core/routes.dart` | GoRouter singleton |
| `activeAccountProvider` | `core/config.dart` | Active KIS account type |
| `appSettingsProvider` | `presentation/settings/settings_controller.dart` | App settings (KIS + Toss config) |

### Adding a New Screen
1. Create `presentation/<feature>/<feature>_screen.dart` + `<feature>_controller.dart`
2. Add `NavDestination` + `GoRoute` in `core/routes.dart`
3. Import screen in `core/routes.dart`

<!-- MANUAL: -->
