<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/presentation/alerts/ — Price Alerts Screen

## Purpose
Price alert CRUD — list active alerts, create new alerts with condition/target/symbol, delete/disable. Exposes `showCreateAlertDialog` as a public top-level function so other screens (e.g., stock detail) can pre-fill it.

## Key Files

| File | Description |
|------|-------------|
| `alerts_screen.dart` | `AlertsScreen` + `showCreateAlertDialog(context, ref, {initialSymbol?, initialMarketCountry?})` |
| `alerts_controller.dart` | `alertsProvider` (`FutureProvider<List<Alert>>`), create/delete/toggle actions |

## For AI Agents

### `showCreateAlertDialog` — Public API
This function is called from `stock_detail_screen.dart` and `alerts_screen.dart` itself:
```dart
showCreateAlertDialog(
  context, ref,
  initialSymbol: 'AAPL',           // optional pre-fill
  initialMarketCountry: 'US',      // optional — drives market toggle
)
```
When `initialMarketCountry` is provided, `manualMarket = true` (user cannot override the market toggle).

### Country Inference
If `initialMarketCountry` is null but `initialSymbol` is non-null, country is inferred: all-digit symbol → 'KR', otherwise → 'US'.

<!-- MANUAL: -->
