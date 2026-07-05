<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/data/api/ — HTTP API Clients

## Purpose
Typed Dart HTTP clients, one per backend resource group. Each file defines model classes (`fromJson`) and a `Provider<XxxApi>` that wraps `dioProvider`. All clients use the shared `_EnvelopeResponse` unwrap pattern from `api_client.dart`.

## Key Files

| File | Description |
|------|-------------|
| `api_client.dart` | Shared `Dio` setup — `_EnvelopeInterceptor` unwraps `{"data":…}` envelope, error handling |
| `portfolio_api.dart` | `UnifiedPortfolio`, `UnifiedPosition`, `UnifiedAccountSummary`, `PlaceOrderRequest`, `BrokerType`, `OrderDirection`, `KisAccount`, `portfolioApiProvider` |
| `stocks_api.dart` | `StockSearchResult`, `StockDetail`, `PricePoint`, `StockQuote`, `FactorData`, `StocksApi`, `stocksApiProvider`, `stockSearchProvider`, `stockDetailProvider` |
| `alerts_api.dart` | `Alert`, `AlertCondition`, `AlertAction`, `alertsApiProvider` |
| `watchlist_api.dart` | `WatchlistCategory`, `WatchlistEntry`, `watchlistApiProvider` |
| `heatmap_api.dart` | `HeatmapSector`, `HeatmapTile`, `heatmapApiProvider` |
| `trade_journal_api.dart` | `TradeJournalEntry`, `JournalAnalysis`, `tradeJournalApiProvider` |
| `principles_api.dart` | `InvestmentPrinciple`, `principlesApiProvider` |
| `settings_api.dart` | `AppSettings`, `KisSettings`, `TossSettings`, `settingsApiProvider` |
| `backtest_api.dart` | `BacktestReport`, `backtestApiProvider` |
| `quant_api.dart` | Quant research data models, `quantApiProvider` |
| `mock_interceptor.dart` | Dio interceptor that returns `mock_fixtures.dart` data (dev only) |
| `mock_fixtures.dart` | Static JSON fixtures for offline development |

## For AI Agents

### Model Parsing Contract
- Use `safeDouble`/`safeDoubleOrNull`/`safeInt` from `parse_utils.dart` for all numeric fields
- Null-guard nested objects: `j['field'] is Map ? SubModel.fromJson(j['field']) : null`
- Null-guard lists: `(j['items'] as List?)?.map(…).toList() ?? []`
- `factor_ranks` map values may be null from backend → guard with `if (e.value != null)`

### Watchlist Symbol Passthrough
`api.addEntry(stockCode: d.symbol, …)` — pass symbol verbatim (e.g., `AAPL`). No transformation.

### Provider Naming Convention
`final fooApiProvider = Provider<FooApi>((ref) => FooApi(ref));`  
Controllers use `ref.read(fooApiProvider)` (not `watch`) for one-shot calls.

<!-- MANUAL: -->
