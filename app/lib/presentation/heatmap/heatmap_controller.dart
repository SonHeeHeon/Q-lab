/// File: app/lib/presentation/heatmap/heatmap_controller.dart
///
/// Riverpod state for Market Heatmap.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/heatmap_api.dart';

final heatmapMarketProvider =
    StateProvider<HeatmapMarket>((ref) => HeatmapMarket.kospi);

final heatmapGroupByProvider =
    StateProvider<HeatmapGroupBy>((ref) => HeatmapGroupBy.sector);

final heatmapDataProvider = FutureProvider<HeatmapResponse>((ref) {
  final m = ref.watch(heatmapMarketProvider);
  final g = ref.watch(heatmapGroupByProvider);
  return ref.read(heatmapApiProvider).getHeatmap(market: m, groupBy: g);
});
