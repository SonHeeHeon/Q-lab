<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/presentation/ — Feature Screens

## Purpose
All Flutter screens and their Riverpod controllers. One subdirectory per feature. Each feature directory contains `<feature>_screen.dart` (UI) and `<feature>_controller.dart` (providers/state).

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `alerts/` | Price alert creation/list screen (see `alerts/AGENTS.md`) |
| `heatmap/` | Market heatmap — live sector heat tiles |
| `home/` | Home/dashboard screen |
| `portfolio/` | Portfolio overview — KR/US positions, account summary, cash |
| `principles/` | Investment principles list/editor |
| `quant/` | Quant research screen — backtest results viewer |
| `settings/` | App settings — KIS/Toss account config, notification prefs |
| `shared/` | Presentation-scoped reusable widgets (order sheet, chart wrappers) |
| `shell/` | Bottom nav shell scaffold |
| `stocks/` | Stock search & detail screens |
| `trade_journal/` | Trade journal — manual entry + LLM summary |
| `watchlist/` | Watchlist categories and entries |

## For AI Agents

### Cross-Feature Shared Widgets (`presentation/shared/`)
| Widget | Purpose |
|--------|---------|
| `order_sheet.dart` → `showOrderSheet()` | Broker-routing buy/sell order sheet |
| `showCreateAlertDialog()` in `alerts/alerts_screen.dart` | Alert creation dialog with `initialSymbol`/`initialMarketCountry` |

### Broker Routing in Screens
KR stocks → `BrokerType.KIS`, `KisAccount.fromWire(activeType.name.toUpperCase())`  
US stocks → `BrokerType.TOSS`, `accountId = appSettingsProvider.valueOrNull?.toss?.accountSeq?.toString()`

### Navigation
Screens navigate via GoRouter: `context.push('/path')` (push) or `context.go('/path')` (replace). Never use `Navigator.push` directly.

<!-- MANUAL: -->
