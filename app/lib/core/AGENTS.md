<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/core/ — App-Wide Configuration & Routing

## Purpose
Houses environment config, GoRouter routing, app theme, and global account/settings state. No business logic — pure wiring.

## Key Files

| File | Description |
|------|-------------|
| `config.dart` | Global providers: `activeAccountProvider` (KisAccountType), `dioProvider` (base Dio) |
| `env.dart` | Compile-time env vars (base URL, WS URL) via `--dart-define` |
| `preferences.dart` | SharedPreferences wrappers — persisted user settings (broker selection, account type) |
| `routes.dart` | GoRouter definition — all `NavDestination`s and `GoRoute`s; shell with bottom nav |
| `theme.dart` | Material 3 `ThemeData` — light/dark schemes, text styles, card shapes |

## For AI Agents

### Routing Pattern
Every navigable screen needs two entries in `routes.dart`:
1. A `NavDestination` in the `_destinations` list (for bottom nav tab)  
   OR just a `GoRoute` under an existing route (for push navigation)
2. A `GoRoute` with `builder:`

URL-encode path parameters containing slashes or special characters:
```dart
context.push('/stocks/${Uri.encodeComponent(code)}')
// decode in GoRoute builder:
code: Uri.decodeComponent(state.pathParameters['code']!)
```

### Account Validation Order (MUST NOT change)
`KisAccount.fromWire` resolution order: PAPER (모의) → REAL → ISA

### Env Vars (dart-define)
| Key | Purpose |
|-----|---------|
| `BASE_URL` | FastAPI backend base URL |
| `WS_URL` | WebSocket quote URL |

<!-- MANUAL: -->
