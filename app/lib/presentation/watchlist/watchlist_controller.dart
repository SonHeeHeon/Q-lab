/// File: app/lib/presentation/watchlist/watchlist_controller.dart
///
/// Riverpod state for the Watchlist screen.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/watchlist_api.dart';

/// Selected category tab. `null` = All.
final selectedCategoryProvider = StateProvider<int?>((ref) => null);

final categoriesProvider = FutureProvider<List<WatchlistCategory>>((ref) {
  return ref.read(watchlistApiProvider).listCategories();
});

final entriesProvider = FutureProvider<List<WatchlistEntry>>((ref) {
  final cid = ref.watch(selectedCategoryProvider);
  return ref.read(watchlistApiProvider).listEntries(categoryId: cid);
});
