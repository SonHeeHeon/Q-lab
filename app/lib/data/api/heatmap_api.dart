/// File: app/lib/data/api/heatmap_api.dart
///
/// Dio wrapper for `/api/heatmap` (PROJECT_BLUEPRINT.md §8.8).
/// Backend ref: `backend/app/api/heatmap.py`.
///
/// Response tree:
///   root → group(s) (sector/industry) → stocks
/// Each node carries `size` (cell weight = market_cap) and
/// `color_value` (percent change). The screen flattens to stocks for
/// rendering but keeps group_id so stocks can be color-grouped.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';

enum HeatmapMarket {
  kospi('KOSPI'),
  kosdaq('KOSDAQ');

  const HeatmapMarket(this.wire);
  final String wire;
}

enum HeatmapGroupBy {
  sector('sector'),
  industry('industry');

  const HeatmapGroupBy(this.wire);
  final String wire;
}

class HeatmapNode {
  HeatmapNode({
    required this.id,
    this.parentId,
    required this.label,
    required this.level, // root | group | stock
    required this.size,
    required this.colorValue,
    required this.meta,
  });

  final String id;
  final String? parentId;
  final String label;
  final String level;
  final double size;
  final double colorValue;
  final Map<String, dynamic> meta;

  bool get isStock => level == 'stock';
  bool get isGroup => level == 'group';
  bool get isRoot => level == 'root';

  String? get stockCode => meta['code'] as String?;
  String? get stockName => meta['name'] as String?;
  double? get marketCap => (meta['market_cap'] as num?)?.toDouble();
  double? get close => (meta['close'] as num?)?.toDouble();
  double? get volume => (meta['volume'] as num?)?.toDouble();
  String? get sector => meta['sector'] as String?;

  factory HeatmapNode.fromJson(Map<String, dynamic> j) => HeatmapNode(
        id: j['id'] as String,
        parentId: j['parent_id'] as String?,
        label: (j['label'] as String?) ?? '',
        level: (j['level'] as String?) ?? 'stock',
        size: (j['size'] as num).toDouble(),
        colorValue: (j['color_value'] as num?)?.toDouble() ?? 0,
        meta: j['meta'] is Map ? asJsonMap(j['meta']) : const {},
      );
}

class HeatmapResponse {
  HeatmapResponse({
    required this.market,
    required this.groupBy,
    this.asOf,
    required this.nodes,
  });

  final String market;
  final String groupBy;
  final DateTime? asOf;
  final List<HeatmapNode> nodes;

  List<HeatmapNode> get stocks => nodes.where((n) => n.isStock).toList();
  List<HeatmapNode> get groups => nodes.where((n) => n.isGroup).toList();

  factory HeatmapResponse.fromJson(Map<String, dynamic> j) => HeatmapResponse(
        market: (j['market'] as String?) ?? '',
        groupBy: (j['group_by'] as String?) ?? '',
        asOf: j['as_of'] == null ? null : DateTime.tryParse(j['as_of'] as String),
        nodes: ((j['nodes'] as List?) ?? const [])
            .map((e) => HeatmapNode.fromJson(asJsonMap(e)))
            .toList(),
      );
}

class HeatmapApi {
  HeatmapApi(this._ref);
  final Ref _ref;

  Future<HeatmapResponse> getHeatmap({
    HeatmapMarket market = HeatmapMarket.kospi,
    HeatmapGroupBy groupBy = HeatmapGroupBy.sector,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/heatmap',
      queryParameters: {'market': market.wire, 'group_by': groupBy.wire},
    );
    return HeatmapResponse.fromJson(asJsonMap(res.data));
  }
}

final heatmapApiProvider = Provider<HeatmapApi>((ref) => HeatmapApi(ref));
