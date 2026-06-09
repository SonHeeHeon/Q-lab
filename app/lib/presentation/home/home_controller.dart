/// File: app/lib/presentation/home/home_controller.dart
///
/// Aggregates Home Dashboard data — unified portfolio (client-side
/// fan-in over 3 KIS accounts) + alerts (skipped gracefully until the
/// `/api/alerts` endpoint ships).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/alerts_api.dart';
import '../../data/api/portfolio_api.dart';
import '../../domain/entities/alert.dart';
import '../../domain/entities/position.dart';

class HomeSnapshot {
  HomeSnapshot({
    required this.balance,
    required this.pendingAlerts,
    required this.triggeredToday,
    required this.topMovers,
    this.alertsAvailable = true,
  });

  final UnifiedBalance balance;
  final List<Alert> pendingAlerts;
  final List<Alert> triggeredToday;
  final List<Position> topMovers;
  final bool alertsAvailable;
}

final homeSnapshotProvider = FutureProvider<HomeSnapshot>((ref) async {
  final portfolioApi = ref.read(portfolioApiProvider);
  final alertsApi = ref.read(alertsApiProvider);

  final balance = await portfolioApi.getUnifiedBalance();

  List<Alert> alerts = const [];
  bool alertsAvailable = true;
  try {
    alerts = await alertsApi.list();
  } catch (_) {
    // Backend `/api/alerts` not yet implemented (Codex TODO).
    alertsAvailable = false;
  }

  final pending = alerts.where((a) => a.status == AlertStatus.pending).toList();

  final now = DateTime.now();
  final triggeredToday = alerts.where((a) {
    final t = a.triggeredAt;
    if (a.status != AlertStatus.triggered || t == null) return false;
    return t.year == now.year && t.month == now.month && t.day == now.day;
  }).toList();

  final movers = [...balance.positions]
    ..sort((a, b) => b.unrealizedPlPct.abs().compareTo(a.unrealizedPlPct.abs()));
  final topMovers = movers.take(3).toList();

  return HomeSnapshot(
    balance: balance,
    pendingAlerts: pending,
    triggeredToday: triggeredToday,
    topMovers: topMovers,
    alertsAvailable: alertsAvailable,
  );
});
