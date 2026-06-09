/// File: app/lib/domain/entities/watchlist.dart
///
/// Role:
///   Dart mirrors of `shared.domain.watchlist.WatchlistCategory` and
///   `WatchlistEntry`.
///
/// Multi-category modeling:
///   A stock in multiple categories appears as multiple WatchlistEntry
///   rows (UNIQUE on (stockCode, categoryId)). UI dedupes when
///   rendering the "All" tab.
///
/// Connected modules:
///   - data/api/watchlist_api.dart
///   - presentation/watchlist/
