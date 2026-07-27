/// File: app/lib/data/api/proposals_api.dart
///
/// Dio wrapper for `/api/proposals*` — the approval-based semi-auto pipeline
/// (PROJECT_BLUEPRINT.md §4.2). Approve routes through the SAME broker safety
/// gateway as manual orders; a blocked approval surfaces as [ApiError]
/// (code `ORDER_BLOCKED`).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/entities/proposal.dart';
import '../../domain/entities/us_advisory.dart';
import 'api_client.dart';

class ProposalsApi {
  ProposalsApi(this._ref);
  final Ref _ref;

  Future<List<Proposal>> list({String? status, DateTime? date}) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/proposals',
      queryParameters: {
        if (status != null) 'status': status,
        if (date != null)
          'date': date.toIso8601String().substring(0, 10),
      },
    );
    final list = res.data as List;
    return list.map((e) => Proposal.fromJson(asJsonMap(e))).toList();
  }

  /// Approves one proposal → broker submit through the safety gateway.
  /// Throws [ApiError] `ORDER_BLOCKED` (403) if the kill switch / daily-loss
  /// limit blocks it; the proposal is left FAILED server-side.
  Future<Proposal> approve(int id) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>('/api/proposals/$id/approve');
    return Proposal.fromJson(asJsonMap(asJsonMap(res.data)['proposal']));
  }

  Future<Proposal> reject(int id) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>('/api/proposals/$id/reject');
    return Proposal.fromJson(asJsonMap(res.data));
  }

  /// Approves every PROPOSED item in a batch (sells first). Returns the
  /// per-batch outcome counts (`submitted`/`blocked`/`failed`).
  Future<Map<String, dynamic>> approveBatch(String batchId) async {
    final dio = _ref.read(dioProvider);
    final res =
        await dio.post<dynamic>('/api/proposals/batches/$batchId/approve-all');
    return asJsonMap(res.data);
  }

  /// Manual trigger for the daily generation batch.
  Future<Map<String, dynamic>> generate({
    String? strategyName,
    bool fullRebalance = false,
    bool sendTelegram = false,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/proposals/generate',
      data: {
        if (strategyName != null) 'strategy_name': strategyName,
        'full_rebalance': fullRebalance,
        'send_telegram': sendTelegram,
      },
    );
    return asJsonMap(res.data);
  }

  /// US 자문(실주문 없음): US 퀀트 방정식 랭킹 vs Toss 보유 → BUY/SELL/HOLD.
  Future<UsAdvisoryResult> usAdvisory(
      {String strategy = 'us_stock_v1', int? topN}) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/proposals/us-advisory',
      queryParameters: {
        'strategy': strategy,
        if (topN != null) 'top_n': topN,
      },
    );
    return UsAdvisoryResult.fromJson(asJsonMap(res.data));
  }
}

final proposalsApiProvider = Provider<ProposalsApi>((ref) => ProposalsApi(ref));
