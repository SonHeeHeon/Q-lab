/// File: app/lib/data/api/trade_journal_api.dart
///
/// Dio wrapper for `/api/trade-journal*` (PROJECT_BLUEPRINT.md §8.3).
/// Backend ref: `backend/app/api/trade_journal.py`.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../parse_utils.dart';
import 'api_client.dart';

class TradeLite {
  TradeLite({
    required this.id,
    required this.accountType,
    required this.stockCode,
    required this.direction,
    required this.quantity,
    required this.price,
    required this.executedAt,
    this.kisOrderNo,
  });

  final int id;
  final String accountType;
  final String stockCode;
  final String direction; // BUY | SELL
  final int quantity;
  final double price;
  final DateTime executedAt;
  final String? kisOrderNo;

  factory TradeLite.fromJson(Map<String, dynamic> j) => TradeLite(
        id: (j['id'] as num).toInt(),
        accountType: j['account_type'] as String,
        stockCode: j['stock_code'] as String,
        direction: j['direction'] as String,
        quantity: (j['quantity'] as num).toInt(),
        price: _d(j['price']),
        executedAt: DateTime.parse(j['executed_at'] as String),
        kisOrderNo: j['kis_order_no'] as String?,
      );
}

class PrincipleLite {
  PrincipleLite({required this.id, required this.title, required this.category});
  final int id;
  final String title;
  final String category;

  factory PrincipleLite.fromJson(Map<String, dynamic> j) => PrincipleLite(
        id: (j['id'] as num).toInt(),
        title: j['title'] as String,
        category: j['category'] as String,
      );
}

class TradeJournal {
  TradeJournal({
    required this.id,
    required this.tradeId,
    required this.direction,
    required this.reason,
    this.postReview,
    required this.createdAt,
    required this.trade,
    required this.appliedPrinciples,
    this.llmAnalysisSummary,
    this.llmViolationTags = const [],
    this.llmAnalyzedAt,
    this.llmAnalysisModel,
  });

  final int id;
  final int tradeId;
  final String direction;
  final String reason;
  final String? postReview;
  final DateTime createdAt;
  final TradeLite trade;
  final List<PrincipleLite> appliedPrinciples;

  /// Direct columns added in Phase 6 — LLM background analyzer writes to
  /// these after a journal entry is created/updated. Null = not yet
  /// analyzed (or analyzer disabled).
  final String? llmAnalysisSummary;
  final List<String> llmViolationTags;
  final DateTime? llmAnalyzedAt;
  final String? llmAnalysisModel;

  /// True if the analyzer has produced output (regardless of verdict).
  bool get hasLlmAnalysis => llmAnalyzedAt != null;

  /// Heuristic verdict for the UI badge:
  ///   - has tags          → violation (red)
  ///   - has summary only  → ok        (green)
  ///   - neither yet       → pending   (placeholder)
  String get llmVerdict {
    if (llmAnalyzedAt == null) return 'pending';
    if (llmViolationTags.isNotEmpty) return 'violation';
    return 'ok';
  }

  factory TradeJournal.fromJson(Map<String, dynamic> j) => TradeJournal(
        id: (j['id'] as num).toInt(),
        tradeId: (j['trade_id'] as num).toInt(),
        direction: j['direction'] as String,
        reason: (j['reason'] as String?) ?? '',
        postReview: j['post_review'] as String?,
        createdAt: DateTime.parse(j['created_at'] as String),
        trade: TradeLite.fromJson(asJsonMap(j['trade'])),
        appliedPrinciples: ((j['applied_principles'] as List?) ?? const [])
            .map((e) => PrincipleLite.fromJson(asJsonMap(e)))
            .toList(),
        llmAnalysisSummary: j['llm_analysis_summary'] as String?,
        llmViolationTags: ((j['llm_violation_tags'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
        llmAnalyzedAt: j['llm_analyzed_at'] == null
            ? null
            : DateTime.tryParse(j['llm_analyzed_at'] as String),
        llmAnalysisModel: j['llm_analysis_model'] as String?,
      );
}

class TradeJournalApi {
  TradeJournalApi(this._ref);
  final Ref _ref;

  Future<List<TradeJournal>> list() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/trade-journal');
    final list = (res.data as List?) ?? const [];
    return list.map((e) => TradeJournal.fromJson(asJsonMap(e))).toList();
  }

  Future<List<TradeLite>> listMissing() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/trade-journal/missing');
    final list = (res.data as List?) ?? const [];
    return list.map((e) => TradeLite.fromJson(asJsonMap(e))).toList();
  }

  /// Create a journal entry for a trade that doesn't yet have one.
  Future<TradeJournal> create({
    required int tradeId,
    required String reason,
    List<int> appliedPrincipleIds = const [],
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/trade-journal',
      data: {
        'trade_id': tradeId,
        'reason': reason,
        'applied_principle_ids': appliedPrincipleIds,
      },
    );
    return TradeJournal.fromJson(asJsonMap(res.data));
  }

  /// Patch an existing journal — any subset of {reason, post_review,
  /// applied_principle_ids}.
  Future<TradeJournal> patch(
    int journalId, {
    String? reason,
    String? postReview,
    List<int>? appliedPrincipleIds,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.patch<dynamic>(
      '/api/trade-journal/$journalId',
      data: {
        if (reason != null) 'reason': reason,
        if (postReview != null) 'post_review': postReview,
        if (appliedPrincipleIds != null) 'applied_principle_ids': appliedPrincipleIds,
      },
    );
    return TradeJournal.fromJson(asJsonMap(res.data));
  }
}

final tradeJournalApiProvider =
    Provider<TradeJournalApi>((ref) => TradeJournalApi(ref));

double _d(Object? v) => safeDouble(v, hint: 'trade_journal');
