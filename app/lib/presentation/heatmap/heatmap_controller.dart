/// File: app/lib/presentation/heatmap/heatmap_controller.dart
///
/// Riverpod state for Market Heatmap with periodic polling.
///
/// `HeatmapNotifier` owns a 3-minute Timer that re-fetches the backend
/// cache (which itself is driven by the new live ATS/REGULAR/AFTER_HOURS
/// pipeline). Toggling market or group_by re-creates the timer cleanly.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/heatmap_api.dart';

const _kPollingInterval = Duration(minutes: 3);

final heatmapMarketProvider =
    StateProvider<HeatmapMarket>((ref) => HeatmapMarket.kospi);

final heatmapGroupByProvider =
    StateProvider<HeatmapGroupBy>((ref) => HeatmapGroupBy.sector);

/// Last successful refresh time on the client side (DateTime.now()), used
/// for the "방금 갱신" relative-time label.
final lastClientRefreshProvider = StateProvider<DateTime?>((ref) => null);

class HeatmapNotifier extends AsyncNotifier<HeatmapResponse> {
  Timer? _timer;
  bool _disposeRegistered = false;

  @override
  Future<HeatmapResponse> build() async {
    final m = ref.watch(heatmapMarketProvider);
    final g = ref.watch(heatmapGroupByProvider);

    // (Re-)schedule polling whenever market/groupBy changes.
    _timer?.cancel();
    _timer = Timer.periodic(_kPollingInterval, (_) => refresh());

    // ref.onDispose is *cumulative* across rebuilds — register only once.
    if (!_disposeRegistered) {
      _disposeRegistered = true;
      ref.onDispose(() {
        _timer?.cancel();
        _timer = null;
      });
    }

    final res = await ref.read(heatmapApiProvider).getHeatmap(market: m, groupBy: g);
    ref.read(lastClientRefreshProvider.notifier).state = DateTime.now();
    return res;
  }

  /// Manual or timer-driven re-fetch. Keeps the previous data visible
  /// while loading (no `state = AsyncLoading()`), so cells animate
  /// smoothly instead of flashing.
  Future<void> refresh() async {
    final m = ref.read(heatmapMarketProvider);
    final g = ref.read(heatmapGroupByProvider);
    final next = await AsyncValue.guard(
      () => ref.read(heatmapApiProvider).getHeatmap(market: m, groupBy: g),
    );
    // Only commit successful refreshes; on error keep the previous data
    // and just log — avoids the screen blanking mid-polling.
    if (next.hasValue) {
      state = next;
      ref.read(lastClientRefreshProvider.notifier).state = DateTime.now();
    } else {
      debugPrint('[heatmap] periodic refresh failed: ${next.error}');
    }
  }
}

final heatmapDataProvider =
    AsyncNotifierProvider<HeatmapNotifier, HeatmapResponse>(HeatmapNotifier.new);
