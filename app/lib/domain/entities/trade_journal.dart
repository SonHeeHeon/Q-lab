/// File: app/lib/domain/entities/trade_journal.dart
///
/// Role:
///   Dart mirror of `shared.domain.trade_journal.TradeJournalEntry`.
///
/// Fields:
///   - id, tradeId, direction
///   - reason (REQUIRED)
///   - appliedPrincipleIds (List<int>)
///   - postReview (nullable)
///   - createdAt
///
/// UI workflow:
///   - The Portfolio screen, on order success, opens an "EntryForm"
///     modal that POSTs this entity. `reason` is validated client-side
///     before allowing submit.
///   - The Trade Journal screen lists entries with joined Trade + Principles.
///
/// Connected modules:
///   - data/api/trade_journal_api.dart
///   - presentation/trade_journal/
///   - presentation/portfolio/ (modal trigger)
