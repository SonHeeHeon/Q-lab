/// File: app/lib/data/api/alerts_api.dart
///
/// Dio wrapper for `/api/alerts*` (PROJECT_BLUEPRINT.md §8.4).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/entities/account.dart';
import '../../domain/entities/alert.dart';
import 'api_client.dart';
import 'portfolio_api.dart' show BrokerType;

/// Alert monitor / auto-order runtime config from `GET /api/alerts/monitor`.
class AlertMonitorSettings {
  AlertMonitorSettings({
    required this.autostart,
    required this.intervalSeconds,
    required this.orderIsMock,
    required this.defaultBroker,
  });

  final bool autostart;
  final int intervalSeconds;

  /// `ALERT_ORDER_IS_MOCK` — when true, BUY/SELL alerts place *simulated*
  /// orders, never real fills. The UI must surface this clearly.
  final bool orderIsMock;
  final String defaultBroker;

  factory AlertMonitorSettings.fromJson(Map<String, dynamic> j) =>
      AlertMonitorSettings(
        autostart: (j['autostart'] as bool?) ?? false,
        intervalSeconds: (j['interval_seconds'] as num?)?.toInt() ?? 0,
        orderIsMock: (j['order_is_mock'] as bool?) ?? true,
        defaultBroker: (j['default_broker'] as String?) ?? 'KIS',
      );
}

class AlertsApi {
  AlertsApi(this._ref);
  final Ref _ref;

  Future<List<Alert>> list({DateTime? from, DateTime? to}) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/alerts',
      queryParameters: {
        if (from != null) 'from': from.toIso8601String(),
        if (to != null) 'to': to.toIso8601String(),
      },
    );
    final list = res.data as List;
    return list.map((e) => Alert.fromJson(asJsonMap(e))).toList();
  }

  /// Creates an alert or a conditional auto-order.
  ///
  /// [symbol] is a 6-digit KR code or a US ticker. [marketCountry] ('KR'/'US')
  /// and [broker] are sent explicitly; if [marketCountry] is null the backend
  /// infers it from the symbol. [action] NOTIFY = alert only; BUY/SELL = place
  /// an order on trigger (requires [orderQuantity]).
  Future<Alert> create({
    required String symbol,
    required AlertCondition condition,
    required double threshold,
    BrokerType broker = BrokerType.KIS,
    String? marketCountry,
    AlertAction action = AlertAction.notify,
    int? orderQuantity,
    KisAccount accountType = KisAccount.paper,
    String? accountId,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/alerts',
      data: {
        'stock_code': symbol,
        'symbol': symbol,
        'condition': condition.wire,
        'threshold': threshold,
        'broker': broker.wire,
        if (marketCountry != null) 'market_country': marketCountry,
        'action': action.wire,
        if (orderQuantity != null) 'order_quantity': orderQuantity,
        'account_type': accountType.wire,
        if (accountId != null && accountId.isNotEmpty) 'account_id': accountId,
      },
    );
    return Alert.fromJson(asJsonMap(res.data));
  }

  /// Reads the alert monitor / auto-order runtime config (mock flag etc.).
  Future<AlertMonitorSettings> monitor() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/alerts/monitor');
    return AlertMonitorSettings.fromJson(asJsonMap(res.data));
  }

  /// Triggers a one-off evaluation of pending alerts (no waiting for the loop).
  Future<Map<String, dynamic>> evaluateOnce() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>('/api/alerts/evaluate');
    return asJsonMap(res.data);
  }

  Future<void> cancel(int id) async {
    final dio = _ref.read(dioProvider);
    await dio.delete<dynamic>('/api/alerts/$id');
  }

  Future<Alert> updatePostMortem(int id, String text) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.patch<dynamic>(
      '/api/alerts/$id/post-mortem',
      data: {'post_mortem': text},
    );
    return Alert.fromJson(asJsonMap(res.data));
  }
}

final alertsApiProvider = Provider<AlertsApi>((ref) => AlertsApi(ref));
