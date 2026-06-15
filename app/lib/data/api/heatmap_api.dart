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

/// Market session, computed by the backend cache pipeline.
///   - PRE_MARKET    : ATS 08:00–09:00 (장전 거래)
///   - REGULAR       : 정규장 09:00–15:30
///   - AFTER_HOURS   : ATS 15:40–20:00 (장후 거래)
///   - CLOSED        : 거래 없음 (장 마감 / 휴장)
enum MarketSession {
  preMarket('PRE_MARKET', '장전 거래', true),
  regular('REGULAR', '정규장', false),
  afterHours('AFTER_HOURS', '장후 거래', true),
  closed('CLOSED', '장 마감', false);

  const MarketSession(this.wire, this.label, this.isExtended);
  final String wire;
  final String label;

  /// True for sessions where liquidity is thin and pricing can be jumpy.
  final bool isExtended;

  static MarketSession fromWire(String? s) {
    if (s == null) return MarketSession.closed;
    final up = s.toUpperCase();
    for (final v in MarketSession.values) {
      if (v.wire == up) return v;
    }
    return MarketSession.closed;
  }
}

enum HeatmapLevel {
  root('root'),
  group('group'),
  stock('stock'),
  unknown('unknown');

  const HeatmapLevel(this.wire);
  final String wire;

  /// Unknown levels become `HeatmapLevel.unknown` and are excluded from
  /// rendering (see `HeatmapResponse.stocks`/`.groups`). Avoids the
  /// historical bug where new server-side level names were silently
  /// treated as stocks and appeared in the treemap as orphan cells.
  static HeatmapLevel fromWire(String? s) {
    if (s == null) return HeatmapLevel.unknown;
    final lower = s.toLowerCase();
    for (final v in HeatmapLevel.values) {
      if (v.wire == lower) return v;
    }
    return HeatmapLevel.unknown;
  }
}

class HeatmapNode {
  HeatmapNode({
    required this.id,
    this.parentId,
    required this.label,
    required this.level,
    required this.size,
    required this.colorValue,
    required this.meta,
  });

  final String id;
  final String? parentId;
  final String label;
  final HeatmapLevel level;
  final double size;
  final double colorValue;
  final Map<String, dynamic> meta;

  bool get isStock => level == HeatmapLevel.stock;
  bool get isGroup => level == HeatmapLevel.group;
  bool get isRoot => level == HeatmapLevel.root;
  bool get isUnknown => level == HeatmapLevel.unknown;

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
        level: HeatmapLevel.fromWire(j['level'] as String?),
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
    this.updatedAt,
    required this.session,
    this.source,
    required this.nodes,
  });

  final String market;
  final String groupBy;
  final DateTime? asOf;

  /// Backend cache pipeline's last refresh timestamp. Distinct from
  /// `asOf` (the trading-day date). Used by the UI for the "X분 전 갱신"
  /// label.
  final DateTime? updatedAt;
  final MarketSession session;
  final String? source;
  final List<HeatmapNode> nodes;

  List<HeatmapNode> get stocks => nodes.where((n) => n.isStock).toList();
  List<HeatmapNode> get groups => nodes.where((n) => n.isGroup).toList();

  factory HeatmapResponse.fromJson(Map<String, dynamic> j) => HeatmapResponse(
        market: (j['market'] as String?) ?? '',
        groupBy: (j['group_by'] as String?) ?? '',
        asOf: j['as_of'] == null ? null : DateTime.tryParse(j['as_of'] as String),
        updatedAt: j['updated_at'] == null
            ? null
            : DateTime.tryParse(j['updated_at'] as String),
        session: MarketSession.fromWire(j['market_session'] as String?),
        source: j['source'] as String?,
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
