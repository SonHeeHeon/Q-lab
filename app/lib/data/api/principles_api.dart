/// File: app/lib/data/api/principles_api.dart
///
/// Dio wrapper for `/api/principles*` (PROJECT_BLUEPRINT.md §8.7).
/// Backend ref: `backend/app/api/principles.py`.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';

enum PrincipleCategory {
  absolute('ABSOLUTE', '절대 원칙'),
  criteria('CRITERIA', '판단 기준'),
  freeNote('FREE_NOTE', '자유 노트');

  const PrincipleCategory(this.wire, this.label);
  final String wire;
  final String label;

  static PrincipleCategory fromWire(String s) =>
      PrincipleCategory.values.firstWhere(
        (e) => e.wire == s.toUpperCase(),
        orElse: () => PrincipleCategory.freeNote,
      );
}

class Principle {
  Principle({
    required this.id,
    required this.title,
    required this.body,
    required this.category,
    required this.isEditable,
    required this.updatedAt,
  });

  final int id;
  final String title;
  final String body;
  final PrincipleCategory category;
  final bool isEditable;
  final DateTime updatedAt;

  factory Principle.fromJson(Map<String, dynamic> j) => Principle(
        id: (j['id'] as num).toInt(),
        title: j['title'] as String,
        body: j['body'] as String,
        category: PrincipleCategory.fromWire(j['category'] as String),
        isEditable: (j['is_editable'] as bool?) ?? true,
        updatedAt: DateTime.parse(j['updated_at'] as String),
      );
}

class PrinciplesApi {
  PrinciplesApi(this._ref);
  final Ref _ref;

  Future<List<Principle>> list({PrincipleCategory? category}) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/principles',
      queryParameters: {if (category != null) 'category': category.wire},
    );
    final list = (res.data as List?) ?? const [];
    return list.map((e) => Principle.fromJson(asJsonMap(e))).toList();
  }

  Future<Principle> create({
    required String title,
    required String body,
    required PrincipleCategory category,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/principles',
      data: {'title': title, 'body': body, 'category': category.wire},
    );
    return Principle.fromJson(asJsonMap(res.data));
  }

  Future<Principle> patch(
    int id, {
    String? title,
    String? body,
    PrincipleCategory? category,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.patch<dynamic>(
      '/api/principles/$id',
      data: {
        if (title != null) 'title': title,
        if (body != null) 'body': body,
        if (category != null) 'category': category.wire,
      },
    );
    return Principle.fromJson(asJsonMap(res.data));
  }

  Future<void> delete(int id) async {
    final dio = _ref.read(dioProvider);
    await dio.delete<dynamic>('/api/principles/$id');
  }
}

final principlesApiProvider = Provider<PrinciplesApi>((ref) => PrinciplesApi(ref));
