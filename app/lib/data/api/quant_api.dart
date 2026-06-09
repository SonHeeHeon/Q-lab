/// File: app/lib/data/api/quant_api.dart
///
/// Dio wrapper for `/api/quant*` (PROJECT_BLUEPRINT.md §8.5).
/// Backend ref: `backend/app/api/quant.py`.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';

class UndervaluedItem {
  UndervaluedItem({
    required this.rank,
    required this.stockCode,
    required this.name,
    required this.market,
    this.sector,
    required this.score,
    this.llmCommentary,
  });

  final int rank;
  final String stockCode;
  final String name;
  final String market;
  final String? sector;
  final double score;
  final String? llmCommentary;

  factory UndervaluedItem.fromJson(Map<String, dynamic> j) => UndervaluedItem(
        rank: (j['rank'] as num).toInt(),
        stockCode: j['stock_code'] as String,
        name: (j['name'] as String?) ?? (j['stock_code'] as String),
        market: (j['market'] as String?) ?? '',
        sector: j['sector'] as String?,
        score: (j['score'] as num).toDouble(),
        llmCommentary: j['llm_commentary'] as String?,
      );
}

class UndervaluedReport {
  UndervaluedReport({
    required this.analysisDate,
    required this.strategyName,
    required this.items,
  });

  final DateTime analysisDate;
  final String strategyName;
  final List<UndervaluedItem> items;

  factory UndervaluedReport.fromJson(Map<String, dynamic> j) => UndervaluedReport(
        analysisDate: DateTime.parse(j['analysis_date'] as String),
        strategyName: (j['strategy_name'] as String?) ?? '',
        items: ((j['items'] as List?) ?? const [])
            .map((e) => UndervaluedItem.fromJson(asJsonMap(e)))
            .toList(),
      );
}

class QuantApi {
  QuantApi(this._ref);
  final Ref _ref;

  Future<UndervaluedReport> getUndervalued({DateTime? date}) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/quant/undervalued',
      queryParameters: {
        if (date != null)
          'date': '${date.year.toString().padLeft(4, '0')}-'
              '${date.month.toString().padLeft(2, '0')}-'
              '${date.day.toString().padLeft(2, '0')}',
      },
    );
    return UndervaluedReport.fromJson(asJsonMap(res.data));
  }
}

final quantApiProvider = Provider<QuantApi>((ref) => QuantApi(ref));
