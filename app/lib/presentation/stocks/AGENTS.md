<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/presentation/stocks/ — Stock Search & Detail

## Purpose
Two-screen feature: `StockSearchScreen` (debounced search with KR/US badge tiles) and `StockDetailScreen` (price chart, factor cards, watchlist toggle, buy/sell, alert). Added in Session A.

## Key Files

| File | Description |
|------|-------------|
| `stock_search_screen.dart` | `StockSearchScreen` — `ConsumerStatefulWidget`, 300ms `Timer` debounce, `_SearchTile` |
| `stock_detail_screen.dart` | `StockDetailScreen` — price/change header, 1-year `fl_chart` line chart, factor cards, holding status, watchlist add, order sheet, alert dialog |
| `stocks_controller.dart` | `stockSearchProvider` (`FutureProvider.family<List, String>`), `stockDetailProvider` (`FutureProvider.family<StockDetail, (String,String)>`) |

## For AI Agents

### Navigation
Search → Detail: `context.push('/stocks/${result.marketCountry}/${Uri.encodeComponent(result.displayCode)}')`  
GoRoute receives: `market = state.pathParameters['market']!`, `code = Uri.decodeComponent(state.pathParameters['code']!)`

### `displayCode` Logic
- US: `symbol` (e.g., `AAPL`) — no transformation, passed as-is to watchlist/order
- KR: `code` (e.g., `005930`)

### Broker Routing in Detail Screen
```dart
// isUs = detail.marketCountry == 'US'
final broker = isUs ? BrokerType.TOSS : BrokerType.KIS;
final kisAccount = isUs ? KisAccount.paper : KisAccount.fromWire(activeType.name.toUpperCase());
final tossAccountId = ref.read(appSettingsProvider).valueOrNull?.toss?.accountSeq?.toString();
```

### Chart (`_PriceChart`)
Uses `fl_chart` `LineChart` on `StockDetail.priceHistory`. Color: change ≥ 0 → `redAccent`, change < 0 → `blueAccent` (Korean convention).

### Factor Cards (`_FactorCard`)
Displays PER/PBR/ROE/ROA. Shows `--` when the value is null. `factor_ranks` map values may be null — guarded in `StockDetail.fromJson`.

<!-- MANUAL: -->
