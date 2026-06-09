/// File: app/lib/data/api/alerts_api.dart
///
/// Dio wrapper for `/api/alerts*` (PROJECT_BLUEPRINT.md §8.4).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/entities/alert.dart';
import 'api_client.dart';

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

  Future<Alert> create({
    required String stockCode,
    required AlertCondition condition,
    required double threshold,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/alerts',
      data: {
        'stock_code': stockCode,
        'condition': condition.wire,
        'threshold': threshold,
      },
    );
    return Alert.fromJson(asJsonMap(res.data));
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
