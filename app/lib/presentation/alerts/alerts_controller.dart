/// File: app/lib/presentation/alerts/alerts_controller.dart
///
/// Riverpod state for the Alerts screen + Home alerts card.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/alerts_api.dart';
import '../../data/ws/quotes_ws_client.dart';
import '../../domain/entities/alert.dart';

enum AlertFilter { all, pending, triggered, cancelled }

final alertFilterProvider = StateProvider<AlertFilter>((ref) => AlertFilter.all);

final alertCalendarViewProvider = StateProvider<bool>((ref) => false);

/// Alert monitor / auto-order runtime config (mock flag, interval, broker).
/// Used by the create form to warn when BUY/SELL orders run in mock mode.
final alertMonitorProvider = FutureProvider<AlertMonitorSettings>((ref) async {
  return ref.read(alertsApiProvider).monitor();
});

final allAlertsProvider = FutureProvider<List<Alert>>((ref) async {
  // Re-fetch whenever WS fires an alert_triggered frame.
  final notifier = ref.read(quotesProvider.notifier);
  final sub = notifier.alertTriggeredStream.listen((_) => ref.invalidateSelf());
  ref.onDispose(sub.cancel);

  final list = await ref.read(alertsApiProvider).list();
  // Sort: pending first (by created_at desc), then triggered (by triggered_at desc),
  // then cancelled
  list.sort((a, b) {
    int statusRank(AlertStatus s) => switch (s) {
          AlertStatus.pending => 0,
          AlertStatus.triggered => 1,
          AlertStatus.cancelled => 2,
        };
    final r = statusRank(a.status).compareTo(statusRank(b.status));
    if (r != 0) return r;
    final at = a.triggeredAt ?? a.createdAt;
    final bt = b.triggeredAt ?? b.createdAt;
    return bt.compareTo(at);
  });
  return list;
});

final filteredAlertsProvider = Provider<List<Alert>>((ref) {
  final all = ref.watch(allAlertsProvider).valueOrNull ?? const <Alert>[];
  final filter = ref.watch(alertFilterProvider);
  return switch (filter) {
    AlertFilter.all => all,
    AlertFilter.pending => all.where((a) => a.status == AlertStatus.pending).toList(),
    AlertFilter.triggered => all.where((a) => a.status == AlertStatus.triggered).toList(),
    AlertFilter.cancelled => all.where((a) => a.status == AlertStatus.cancelled).toList(),
  };
});
