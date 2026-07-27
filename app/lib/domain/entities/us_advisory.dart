/// File: app/lib/domain/entities/us_advisory.dart
///
/// US 자문 슬리브 모델 — `/api/proposals/us-advisory` 응답. 자문 전용이며
/// 실주문/승인 파이프라인과 무관하다(Toss 라이브 주문 미연동).
library;

class UsAdvisoryItem {
  const UsAdvisoryItem({
    required this.ticker,
    required this.action,
    required this.rank,
    required this.targetWeight,
    required this.heldQty,
    required this.reason,
  });

  final String ticker;
  final String action; // BUY | HOLD | SELL
  final int? rank;
  final double targetWeight;
  final int heldQty;
  final String reason;

  factory UsAdvisoryItem.fromJson(Map<String, dynamic> j) => UsAdvisoryItem(
        ticker: (j['ticker'] ?? '').toString(),
        action: (j['action'] ?? '').toString(),
        rank: j['rank'] == null ? null : (j['rank'] as num).toInt(),
        targetWeight: (j['target_weight'] as num?)?.toDouble() ?? 0,
        heldQty: (j['held_qty'] as num?)?.toInt() ?? 0,
        reason: (j['reason'] ?? '').toString(),
      );
}

class UsAdvisoryResult {
  const UsAdvisoryResult({
    required this.asOf,
    required this.strategy,
    required this.universe,
    required this.targetN,
    required this.tossConfigured,
    required this.items,
  });

  final String asOf;
  final String strategy;
  final String universe;
  final int targetN;
  final bool tossConfigured;
  final List<UsAdvisoryItem> items;

  List<UsAdvisoryItem> get buys =>
      items.where((i) => i.action == 'BUY').toList();
  List<UsAdvisoryItem> get holds =>
      items.where((i) => i.action == 'HOLD').toList();
  List<UsAdvisoryItem> get sells =>
      items.where((i) => i.action == 'SELL').toList();

  factory UsAdvisoryResult.fromJson(Map<String, dynamic> j) => UsAdvisoryResult(
        asOf: (j['as_of'] ?? '').toString(),
        strategy: (j['strategy'] ?? '').toString(),
        universe: (j['universe'] ?? '').toString(),
        targetN: (j['target_n'] as num?)?.toInt() ?? 0,
        tossConfigured: j['toss_configured'] == true,
        items: ((j['advisory'] as List?) ?? const [])
            .map((e) => UsAdvisoryItem.fromJson(
                Map<String, dynamic>.from(e as Map)))
            .toList(),
      );
}
