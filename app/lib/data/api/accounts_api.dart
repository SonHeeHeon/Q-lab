/// File: app/lib/data/api/accounts_api.dart
///
/// 계좌 프로파일 API — 목록/타입 마킹/퀀트 토글/슬리브 비중.
/// 실계좌 퀀트 ON은 라이브 잠금 중 백엔드가 403으로 거부한다(서버가 진실).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';

class SleeveConfig {
  SleeveConfig({
    required this.type,
    this.name,
    this.code,
    required this.weight,
  });

  /// 'strategy' | 'hold'
  final String type;
  final String? name;
  final String? code;
  final double weight;

  String get label =>
      type == 'hold' ? '고정보유 ${code ?? '?'}' : (name ?? '?');

  SleeveConfig copyWith({double? weight}) => SleeveConfig(
        type: type,
        name: name,
        code: code,
        weight: weight ?? this.weight,
      );

  factory SleeveConfig.fromJson(Map<String, dynamic> json) => SleeveConfig(
        type: (json['type'] as String?) ?? 'strategy',
        name: json['name'] as String?,
        code: json['code'] as String?,
        weight: ((json['weight'] as num?) ?? 0).toDouble(),
      );

  Map<String, dynamic> toJson() => {
        'type': type,
        if (name != null) 'name': name,
        if (code != null) 'code': code,
        'weight': weight,
      };
}

/// 계좌에 추가 가능한 전략 항목 ('슬리브 추가' 바텀시트용 카탈로그).
class SleeveCatalogEntry {
  SleeveCatalogEntry({
    required this.name,
    this.universe,
    this.description = '',
  });

  final String name;
  final String? universe;
  final String description;

  factory SleeveCatalogEntry.fromJson(Map<String, dynamic> json) =>
      SleeveCatalogEntry(
        name: json['name'] as String,
        universe: json['universe'] as String?,
        description: (json['description'] as String?) ?? '',
      );
}

class AccountProfileInfo {
  AccountProfileInfo({
    required this.accountKey,
    required this.broker,
    this.accountType,
    required this.profileType,
    required this.quantEnabled,
    required this.connected,
    required this.sleeves,
    this.availableSleeves = const [],
    this.holdAllowed = true,
  });

  final String accountKey;
  final String broker;
  final String? accountType;
  final String profileType;
  final bool quantEnabled;
  final bool connected;
  final List<SleeveConfig> sleeves;
  final List<SleeveCatalogEntry> availableSleeves;
  final bool holdAllowed;

  factory AccountProfileInfo.fromJson(Map<String, dynamic> json) =>
      AccountProfileInfo(
        accountKey: json['account_key'] as String,
        broker: json['broker'] as String,
        accountType: json['account_type'] as String?,
        profileType: (json['profile_type'] as String?) ?? 'PERSONAL',
        quantEnabled: (json['quant_enabled'] as bool?) ?? false,
        connected: (json['connected'] as bool?) ?? false,
        sleeves: ((json['sleeves'] as List?) ?? const [])
            .map((e) => SleeveConfig.fromJson(e as Map<String, dynamic>))
            .toList(),
        availableSleeves: ((json['available_sleeves'] as List?) ?? const [])
            .map((e) => SleeveCatalogEntry.fromJson(e as Map<String, dynamic>))
            .toList(),
        holdAllowed: (json['hold_allowed'] as bool?) ?? true,
      );
}

class AccountsApi {
  AccountsApi(this._ref);
  final Ref _ref;

  Future<List<AccountProfileInfo>> list() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/accounts');
    final data = res.data;
    final rows = data is List ? data : const [];
    return rows
        .map((e) => AccountProfileInfo.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> patch(
    String accountKey, {
    String? profileType,
    bool? quantEnabled,
    List<SleeveConfig>? sleeves,
  }) async {
    final dio = _ref.read(dioProvider);
    await dio.patch<dynamic>(
      '/api/accounts/$accountKey',
      data: {
        if (profileType != null) 'profile_type': profileType,
        if (quantEnabled != null) 'quant_enabled': quantEnabled,
        if (sleeves != null)
          'sleeves': sleeves.map((s) => s.toJson()).toList(),
      },
    );
  }
}

final accountsApiProvider = Provider<AccountsApi>((ref) => AccountsApi(ref));

final accountsProvider = FutureProvider<List<AccountProfileInfo>>(
  (ref) => ref.read(accountsApiProvider).list(),
);
