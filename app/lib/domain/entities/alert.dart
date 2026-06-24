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

/// What happens when an alert's condition fires.
///   - notify : 알림만 보냄 (텔레그램/푸시)
///   - buy/sell: 조건 발동 시 주문까지 자동 생성 (조건부 주문)
enum AlertAction {
  notify('NOTIFY', '알림'),
  buy('BUY', '매수'),
  sell('SELL', '매도');

  const AlertAction(this.wire, this.label);
  final String wire;
  final String label;

  /// True for actions that place an order (BUY/SELL) — these require a
  /// quantity. NOTIFY is alert-only.
  bool get isOrder => this != AlertAction.notify;

  static AlertAction fromWire(String? s) => AlertAction.values.firstWhere(
        (e) => e.wire == (s ?? '').toUpperCase(),
        orElse: () => AlertAction.notify,
      );
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
    this.broker = 'KIS',
    this.marketCountry = 'KR',
    this.symbol = '',
    this.action = AlertAction.notify,
    this.orderQuantity,
    this.accountType,
    this.accountId,
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

  /// Broker wire ('KIS' / 'TOSS') the alert/order is bound to.
  final String broker;

  /// 'KR' (국장) or 'US' (나스닥/뉴욕).
  final String marketCountry;

  /// Resolved symbol — 6-digit KR code or US ticker. Falls back to stockCode.
  final String symbol;

  /// NOTIFY = 알림만, BUY/SELL = 조건부 주문.
  final AlertAction action;

  /// Order quantity for BUY/SELL actions (null for NOTIFY).
  final int? orderQuantity;

  /// KIS account type wire ('PAPER'/'REAL'/'ISA'), null for non-KIS.
  final String? accountType;

  /// Toss account sequence, null for KIS.
  final String? accountId;

  bool get isUsMarket => marketCountry.toUpperCase() == 'US';

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
        broker: (json['broker'] as String?) ?? 'KIS',
        marketCountry: (json['market_country'] as String?) ?? 'KR',
        symbol: (json['symbol'] as String?) ?? (json['stock_code'] as String),
        action: AlertAction.fromWire(json['action'] as String?),
        orderQuantity: (json['order_quantity'] as num?)?.toInt(),
        accountType: json['account_type'] as String?,
        accountId: json['account_id'] as String?,
      );
}
