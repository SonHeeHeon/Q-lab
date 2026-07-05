<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/presentation/watchlist/ — Watchlist

## Purpose
Watchlist category management and entry list. Users can create categories, add/remove stocks, and view live-priced watchlist entries. Adding from `StockDetailScreen` auto-creates "기본 관심종목" if no categories exist.

## Key Files

| File | Description |
|------|-------------|
| `watchlist_screen.dart` | `WatchlistScreen` — category tabs, entry tiles with live price, add/remove actions |
| `watchlist_controller.dart` | `watchlistCategoriesProvider`, `watchlistEntriesProvider`, category/entry CRUD actions |

## For AI Agents

### Auto-Create Default Category
When adding from stock detail and no categories exist:
```dart
final cats = await api.listCategories();
final categoryId = cats.isEmpty
  ? (await api.createCategory(name: '기본 관심종목')).id
  : (cats.length == 1 ? cats.first.id : await _pickCategory(context, cats));
await api.addEntry(stockCode: symbol, categoryId: categoryId);
```

### Symbol Passthrough
`stockCode` is passed verbatim — AAPL stays AAPL, 005930 stays 005930. No normalization.

<!-- MANUAL: -->
