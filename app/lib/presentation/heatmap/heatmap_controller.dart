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

  /// Small debounce so rapid SegmentedButton clicks (KOSPI ↔ KOSDAQ ↔
  /// 섹터 ↔ 산업) collapse into a single fetch instead of overwhelming
  /// the backend.
  static const _kToggleDebounce = Duration(milliseconds: 300);

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

    // Wait a short tick so consecutive toggles get coalesced into a
    // single network call. If the build is canceled by another toggle
    // before the delay completes, the in-flight Future is discarded
    // by Riverpod and the next build wins.
    await Future<void>.delayed(_kToggleDebounce);

    final res = await ref.read(heatmapApiProvider).getHeatmap(market: m, groupBy: g);
    ref.read(lastClientRefreshProvider.notifier).state = DateTime.now();
    return res;
  }

  /// Manual or timer-driven re-fetch. Keeps the previous data visible
  /// while loading (no `state = AsyncLoading()`), so cells animate
  /// smoothly instead of flashing.
  ///
  /// [force] maps to the backend `force_refresh` flag: the periodic timer
  /// calls `refresh()` (force=false, serves cache); the toolbar's manual
  /// refresh button calls `refresh(force: true)` to force an upstream pull.
  Future<void> refresh({bool force = false}) async {
    final m = ref.read(heatmapMarketProvider);
    final g = ref.read(heatmapGroupByProvider);
    final next = await AsyncValue.guard(
      () => ref
          .read(heatmapApiProvider)
          .getHeatmap(market: m, groupBy: g, forceRefresh: force),
    );
    // Only commit successful refreshes; on error keep the previous data
    // and just log — avoids the screen blanking mid-polling.
    if (next.hasValue) {
      state = next;
      ref.read(lastClientRefreshProvider.notifier).state = DateTime.now();
    } else {
      debugPrint('[heatmap] refresh failed (force=$force): ${next.error}');
    }
  }
}

final heatmapDataProvider =
    AsyncNotifierProvider<HeatmapNotifier, HeatmapResponse>(HeatmapNotifier.new);
