/// File: app/lib/domain/entities/stock.dart
///
/// Role:
///   Dart mirror of `shared.domain.stock.Stock` (Python Pydantic).
///   Immutable value object representing one tradeable security.
///
/// Fields (planned):
///   - code (e.g. "005930")
///   - name
///   - market (KOSPI | KOSDAQ)
///   - sector, industry
///   - listedAt, delistedAt
///   - isDelisted
///
/// Connected modules:
///   - data/api/*  (deserialize from JSON)
///   - presentation/* (every screen that shows a stock)
