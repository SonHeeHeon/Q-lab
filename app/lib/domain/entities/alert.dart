/// File: app/lib/domain/entities/alert.dart
///
/// Dart mirror of `shared.domain.alert.Alert` + `AlertCondition` enum.
library;

enum AlertCondition {
  priceAbove('PRICE_ABOVE'),
  priceBelow('PRICE_BELOW'),
  pctChange('PCT_CHANGE'),
  volumeSpike('VOLUME_SPIKE');

  const AlertCondition(this.wire);
  final String wire;

  /// Unknown wire values fall back to `priceAbove` (safest non-action default).
  /// Backend additions surface as graceful fallback instead of a crash.
  static AlertCondition fromWire(String s) =>
      AlertCondition.values.firstWhere(
        (e) => e.wire == s.toUpperCase(),
        orElse: () => AlertCondition.priceAbove,
      );

  String get label => switch (this) {
        AlertCondition.priceAbove => '가격 ≥',
        AlertCondition.priceBelow => '가격 ≤',
        AlertCondition.pctChange => '변동률',
        AlertCondition.volumeSpike => '거래량 급증',
      };
}

enum AlertStatus { pending, triggered, cancelled }

class Alert {
  Alert({
    required this.id,
    required this.stockCode,
    required this.stockName,
    required this.condition,
    required this.threshold,
    required this.status,
    required this.createdAt,
    this.triggeredAt,
    this.postMortem,
  });

  final int id;
  final String stockCode;
  final String stockName;
  final AlertCondition condition;
  final double threshold;
  final AlertStatus status;
  final DateTime createdAt;
  final DateTime? triggeredAt;
  final String? postMortem;

  factory Alert.fromJson(Map<String, dynamic> json) => Alert(
        id: json['id'] as int,
        stockCode: json['stock_code'] as String,
        stockName: json['stock_name'] as String,
        condition: AlertCondition.fromWire(json['condition'] as String),
        threshold: (json['threshold'] as num).toDouble(),
        status: AlertStatus.values.byName((json['status'] as String).toLowerCase()),
        createdAt: DateTime.parse(json['created_at'] as String),
        triggeredAt: json['triggered_at'] == null
            ? null
            : DateTime.parse(json['triggered_at'] as String),
        postMortem: json['post_mortem'] as String?,
      );
}
