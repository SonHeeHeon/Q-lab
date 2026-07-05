<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/data/ws/ — WebSocket Client

## Purpose
Real-time quote WebSocket client. Connects to the backend `/ws/quotes` endpoint and emits a `Stream<QuoteTick>` consumed by portfolio and heatmap screens.

## Key Files

| File | Description |
|------|-------------|
| `quotes_ws_client.dart` | `QuoteTick` model, `QuotesWsClient`, `quotesProvider` (`StreamProvider<QuoteTick>`) |

## For AI Agents

### Tick Format
```dart
class QuoteTick {
  final String ticker;
  final double price;
  final double change;
  final double changeRate;
  final String currency;   // "KRW" or "USD"
  final DateTime timestamp;
}
```

### Currency Routing
`currency == "USD"` → tick is native USD price; convert via `usdToKrw(price, fxRate)` for KRW display.  
`currency == "KRW"` → display directly.

### Usage in Screens
```dart
final tick = ref.watch(quotesProvider.select((s) => s.valueOrNull));
final livePrice = tick?.ticker == myTicker ? tick!.price : null;
```

<!-- MANUAL: -->
