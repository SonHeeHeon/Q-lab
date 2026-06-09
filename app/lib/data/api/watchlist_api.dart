/// File: app/lib/data/api/watchlist_api.dart
///
/// Dio wrapper for `/api/watchlist*` (PROJECT_BLUEPRINT.md §8.2).
/// Backend ref: `backend/app/api/watchlist.py`.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';

class WatchlistCategory {
  WatchlistCategory({
    required this.id,
    required this.name,
    required this.color,
    required this.sortOrder,
  });

  final int id;
  final String name;
  final String color; // hex like "#888888"
  final int sortOrder;

  factory WatchlistCategory.fromJson(Map<String, dynamic> j) => WatchlistCategory(
        id: (j['id'] as num).toInt(),
        name: j['name'] as String,
        color: (j['color'] as String?) ?? '#888888',
        sortOrder: (j['sort_order'] as num?)?.toInt() ?? 0,
      );
}

class WatchlistEntry {
  WatchlistEntry({
    required this.id,
    required this.stockCode,
    required this.categoryId,
    required this.reason,
    required this.addedAt,
  });

  final int id;
  final String stockCode;
  final int categoryId;
  final String reason;
  final DateTime addedAt;

  factory WatchlistEntry.fromJson(Map<String, dynamic> j) => WatchlistEntry(
        id: (j['id'] as num).toInt(),
        stockCode: j['stock_code'] as String,
        categoryId: (j['category_id'] as num).toInt(),
        reason: (j['reason'] as String?) ?? '',
        addedAt: DateTime.parse(j['added_at'] as String),
      );
}

class WatchlistApi {
  WatchlistApi(this._ref);
  final Ref _ref;

  // ----- categories ---------------------------------------------------------

  Future<List<WatchlistCategory>> listCategories() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/watchlist/categories');
    final list = (res.data as List?) ?? const [];
    return list.map((e) => WatchlistCategory.fromJson(asJsonMap(e))).toList();
  }

  Future<WatchlistCategory> createCategory({
    required String name,
    String color = '#888888',
    int sortOrder = 0,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/watchlist/categories',
      data: {'name': name, 'color': color, 'sort_order': sortOrder},
    );
    return WatchlistCategory.fromJson(asJsonMap(res.data));
  }

  Future<WatchlistCategory> updateCategory(
    int id, {
    String? name,
    String? color,
    int? sortOrder,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.patch<dynamic>(
      '/api/watchlist/categories/$id',
      data: {
        if (name != null) 'name': name,
        if (color != null) 'color': color,
        if (sortOrder != null) 'sort_order': sortOrder,
      },
    );
    return WatchlistCategory.fromJson(asJsonMap(res.data));
  }

  Future<void> deleteCategory(int id) async {
    final dio = _ref.read(dioProvider);
    await dio.delete<dynamic>('/api/watchlist/categories/$id');
  }

  // ----- entries ------------------------------------------------------------

  Future<List<WatchlistEntry>> listEntries({int? categoryId}) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/watchlist/entries',
      queryParameters: {if (categoryId != null) 'category_id': categoryId},
    );
    final list = (res.data as List?) ?? const [];
    return list.map((e) => WatchlistEntry.fromJson(asJsonMap(e))).toList();
  }

  Future<WatchlistEntry> addEntry({
    required String stockCode,
    required int categoryId,
    required String reason,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/watchlist/entries',
      data: {'stock_code': stockCode, 'category_id': categoryId, 'reason': reason},
    );
    return WatchlistEntry.fromJson(asJsonMap(res.data));
  }

  Future<WatchlistEntry> updateEntryReason(int id, String reason) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.patch<dynamic>(
      '/api/watchlist/entries/$id',
      data: {'reason': reason},
    );
    return WatchlistEntry.fromJson(asJsonMap(res.data));
  }

  Future<void> deleteEntry(int id) async {
    final dio = _ref.read(dioProvider);
    await dio.delete<dynamic>('/api/watchlist/entries/$id');
  }
}

final watchlistApiProvider = Provider<WatchlistApi>((ref) => WatchlistApi(ref));
