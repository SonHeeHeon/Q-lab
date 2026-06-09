/// File: app/lib/domain/entities/trade.dart
///
/// Role:
///   Dart mirror of `shared.domain.trade.Trade`. Returned by the
///   Portfolio API after a successful place_order call.
///
/// Fields:
///   - id, accountType, stockCode, direction (BUY|SELL)
///   - quantity, price
///   - executedAt, kisOrderNo
///
/// UX rule:
///   On receiving a fresh Trade, the Portfolio controller MUST
///   immediately open the Trade Journal modal to capture reason.
///
/// Connected modules:
///   - data/api/portfolio_api.dart (return type)
///   - presentation/portfolio/ (modal trigger)
///   - presentation/trade_journal/ (form references this)
