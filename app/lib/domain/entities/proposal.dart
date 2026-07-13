/// File: app/lib/domain/entities/proposal.dart
///
/// Order proposal from the approval-based semi-auto pipeline
/// (PROJECT_BLUEPRINT.md §4.2). The backend generates these daily from the
/// promoted equation + validated intra-period rules; the user approves or
/// rejects each in-app, and only then does an order reach the broker.
library;

import '../../data/api/api_client.dart' show asJsonMap;

/// Lifecycle mirrors backend `order_proposals.status`.
enum ProposalStatus {
  proposed,
  approved,
  submitted,
  filled,
  rejected,
  expired,
  failed;

  static ProposalStatus fromWire(String s) => values.firstWhere(
        (e) => e.name.toUpperCase() == s.toUpperCase(),
        orElse: () => ProposalStatus.proposed,
      );

  String get label => switch (this) {
        ProposalStatus.proposed => '대기',
        ProposalStatus.approved => '승인됨',
        ProposalStatus.submitted => '제출됨',
        ProposalStatus.filled => '체결',
        ProposalStatus.rejected => '거절',
        ProposalStatus.expired => '만료',
        ProposalStatus.failed => '실패',
      };

  bool get isActionable => this == ProposalStatus.proposed;
}

class Proposal {
  Proposal({
    required this.id,
    required this.batchId,
    required this.proposalDate,
    required this.accountType,
    required this.strategyName,
    required this.stockCode,
    required this.market,
    required this.side,
    required this.qty,
    required this.limitPrice,
    required this.lastPrice,
    required this.estimatedNotional,
    required this.reason,
    required this.status,
    required this.expiresAt,
    required this.tradeId,
    required this.createdAt,
  });

  final int id;
  final String batchId;
  final DateTime proposalDate;
  final String accountType;
  final String strategyName;
  final String stockCode;
  final String market;

  /// 'BUY' | 'SELL'.
  final String side;
  final int qty;
  final double? limitPrice;
  final double? lastPrice;
  final double? estimatedNotional;

  /// Rule metadata: `{"rule": "BAND_TRIM", ...}`. Drives the reason chip.
  final Map<String, dynamic> reason;
  final ProposalStatus status;
  final DateTime? expiresAt;
  final int? tradeId;
  final DateTime createdAt;

  bool get isBuy => side.toUpperCase() == 'BUY';

  /// Human label for the rule that produced this proposal.
  String get ruleLabel {
    final rule = (reason['rule'] as String?)?.toUpperCase() ?? '';
    return switch (rule) {
      'STOP_LOSS' => '손절',
      'TAKE_PROFIT' => '익절',
      'BAND_TRIM' => '비중 트림',
      'SCORE_EXIT' => '점수 이탈',
      'REGIME_DERISK' => '레짐 축소',
      'REBALANCE' => '리밸런스',
      _ => rule.isEmpty ? '제안' : rule,
    };
  }

  factory Proposal.fromJson(Map<String, dynamic> j) => Proposal(
        id: (j['id'] as num).toInt(),
        batchId: j['batch_id']?.toString() ?? '',
        proposalDate: DateTime.parse(j['proposal_date'].toString()),
        accountType: j['account_type']?.toString() ?? 'PAPER',
        strategyName: j['strategy_name']?.toString() ?? '',
        stockCode: j['stock_code']?.toString() ?? '',
        market: j['market']?.toString() ?? 'KR',
        side: j['side']?.toString() ?? 'BUY',
        qty: (j['qty'] as num?)?.toInt() ?? 0,
        limitPrice: (j['limit_price'] as num?)?.toDouble(),
        lastPrice: (j['last_price'] as num?)?.toDouble(),
        estimatedNotional: (j['estimated_notional'] as num?)?.toDouble(),
        reason: j['reason'] is Map ? asJsonMap(j['reason']) : <String, dynamic>{},
        status: ProposalStatus.fromWire(j['status']?.toString() ?? 'PROPOSED'),
        expiresAt: j['expires_at'] != null
            ? DateTime.tryParse(j['expires_at'].toString())
            : null,
        tradeId: (j['trade_id'] as num?)?.toInt(),
        createdAt: DateTime.parse(j['created_at'].toString()),
      );
}
