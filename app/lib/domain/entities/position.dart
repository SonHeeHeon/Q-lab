/// File: app/lib/domain/entities/position.dart
///
/// Dart mirror of `backend.app.schemas.portfolio.PositionResponse`.
/// Numeric fields arrive as JSON STRINGS because the Pydantic schema
/// uses `Decimal`. We coerce here so callers always see `double`.
library;

import '../../data/parse_utils.dart';
import 'account.dart';

class Position {
  Position({
    required this.accountType,
    required this.stockCode,
    required this.stockName,
    required this.quantity,
    required this.avgBuyPrice,
    this.currentPrice,
    this.unrealizedPlOverride,
    this.unrealizedPlPctOverride,
  });

  final KisAccount accountType;
  final String stockCode;
  final String stockName;
  final int quantity;
  final double avgBuyPrice;

  /// Patched live by the quotes WS stream. Null until first tick lands.
  double? currentPrice;

  /// When the backend ships unrealized_pl directly we trust it over our
  /// local recompute (KIS includes commission/tax adjustments).
  final double? unrealizedPlOverride;
  final double? unrealizedPlPctOverride;

  double get marketValue => (currentPrice ?? avgBuyPrice) * quantity;
  double get costBasis => avgBuyPrice * quantity;
  double get unrealizedPl => unrealizedPlOverride ?? (marketValue - costBasis);
  double get unrealizedPlPct =>
      unrealizedPlPctOverride ??
      (costBasis == 0 ? 0 : (unrealizedPl / costBasis) * 100);

  /// [accountType] must be threaded in by the parent PortfolioResponse —
  /// backend's PositionResponse does not embed it per-row.
  factory Position.fromJson(Map<String, dynamic> json, KisAccount accountType) =>
      Position(
        accountType: accountType,
        stockCode: (json['stock_code'] ?? '') as String,
        stockName: (json['name'] ?? json['stock_name'] ?? '') as String,
        quantity: _toInt(json['quantity']),
        avgBuyPrice: _toDouble(json['avg_buy_price']),
        currentPrice: _toDoubleOrNull(json['current_price']),
        unrealizedPlOverride: _toDoubleOrNull(json['unrealized_pl']),
        unrealizedPlPctOverride: _toDoubleOrNull(json['unrealized_pl_rate']),
      );
}

// Pydantic emits Decimal as JSON STRING (e.g. "10000000", "0E-8").
// Centralised in lib/data/parse_utils.dart so unexpected payloads
// produce a debug log instead of silently coercing to 0.
double _toDouble(Object? v) => safeDouble(v, hint: 'position');
double? _toDoubleOrNull(Object? v) => safeDoubleOrNull(v, hint: 'position');
int _toInt(Object? v) => safeInt(v, hint: 'position.qty');
