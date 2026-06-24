/// File: app/lib/presentation/stocks/stocks_controller.dart
///
/// Riverpod providers for stock search and detail.
/// Debounce is handled in the widget (Timer 300ms); these providers are
/// pure fetch-on-call.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/stocks_api.dart';

/// Search results keyed by the query string.
/// Returns empty list immediately for blank queries.
final stockSearchProvider =
    FutureProvider.family<List<StockSearchResult>, String>((ref, query) {
  if (query.isEmpty) return Future.value(const []);
  return ref.read(stocksApiProvider).search(query);
});

/// Detail keyed by (market, code) — e.g. ('KR','005930') or ('US','AAPL').
final stockDetailProvider =
    FutureProvider.family<StockDetail, (String, String)>((ref, args) {
  return ref.read(stocksApiProvider).detail(args.$1, args.$2);
});
