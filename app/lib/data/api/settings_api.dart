/// File: app/lib/data/api/settings_api.dart
///
/// Dio wrapper for `/api/settings*` (PROJECT_BLUEPRINT.md §8.9).
///
/// Secret handling: GET returns masked strings (`••••••••`). The real
/// value only travels from client → server in update/save calls.
library;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/entities/account.dart';
import 'api_client.dart';

class KisAccountStatus {
  KisAccountStatus({
    required this.type,
    required this.hasCredentials,
    required this.tokenValid,
    this.lastTokenIssuedAt,
    this.lastError,
    this.accountNoMasked,
  });

  final KisAccount type;
  final bool hasCredentials;
  final bool tokenValid;
  final DateTime? lastTokenIssuedAt;
  final String? lastError;
  final String? accountNoMasked;

  bool get isActive => hasCredentials && tokenValid;

  factory KisAccountStatus.fromJson(Map<String, dynamic> j) => KisAccountStatus(
        type: KisAccount.fromWire(j['account_type'] as String),
        hasCredentials: (j['has_credentials'] as bool?) ?? false,
        tokenValid: (j['token_valid'] as bool?) ?? false,
        lastTokenIssuedAt: j['last_token_issued_at'] == null
            ? null
            : DateTime.tryParse(j['last_token_issued_at'] as String),
        lastError: j['last_error'] as String?,
        accountNoMasked: j['account_no_masked'] as String?,
      );
}

class AppSettings {
  AppSettings({
    required this.accounts,
    required this.defaultDropThresholdPct,
    required this.telegramChatId,
    required this.telegramTokenMasked,
    required this.llmProvider,
    required this.llmModel,
    required this.llmApiKeyMasked,
    required this.llmCacheTtlHours,
    this.llmCommentaryMode = 'on_view',
    required this.ratingStrategyName,
    required this.etfStrategyName,
    required this.sleeveEtfWeight,
    this.toss,
  });

  final List<KisAccountStatus> accounts;
  final double defaultDropThresholdPct;
  final String? telegramChatId;
  final String telegramTokenMasked;
  final String llmProvider;
  final String llmModel;
  final String llmApiKeyMasked;
  final int llmCacheTtlHours;

  /// LLM 실행 정책 — 'on_view'(조회 시 1회 생성, 기본) | 'scheduled'(크론).
  final String llmCommentaryMode;

  /// Strategy preset used by the ratings batch (`backend/app/services/
  /// batch/rating_batch.py`, `Setting` key `rating_strategy_name`). Falls
  /// back to the backend's own default (`DEFAULT_STRATEGY_NAME`).
  final String ratingStrategyName;

  /// ETF-sleeve strategy preset (two-sleeve rollout, 2026-07-25 plan).
  /// Falls back to the backend's own default (`DEFAULT_ETF_STRATEGY_NAME`).
  final String etfStrategyName;

  /// Fraction (0.0–1.0) of account NAV run by the ETF sleeve; the stock
  /// sleeve gets `1 - sleeveEtfWeight`. Clamped defensively so a malformed
  /// value can never crash the settings screen's `Slider` (min 0 / max 1).
  final double sleeveEtfWeight;
  final TossSettings? toss;

  factory AppSettings.fromJson(Map<String, dynamic> j) => AppSettings(
        accounts: ((j['accounts'] as List?) ?? const [])
            .map((e) => KisAccountStatus.fromJson(asJsonMap(e)))
            .toList(),
        defaultDropThresholdPct:
            (j['default_drop_threshold_pct'] as num?)?.toDouble() ?? 5.0,
        telegramChatId: j['telegram_chat_id'] as String?,
        telegramTokenMasked: (j['telegram_token_masked'] as String?) ?? '',
        llmProvider: (j['llm_provider'] as String?) ?? 'openai',
        llmModel: (j['llm_model'] as String?) ?? 'gpt-4o',
        llmApiKeyMasked: (j['llm_api_key_masked'] as String?) ?? '',
        llmCacheTtlHours: (j['llm_cache_ttl_hours'] as num?)?.toInt() ?? 24,
        llmCommentaryMode: (j['llm_commentary_mode'] as String?) ?? 'on_view',
        ratingStrategyName:
            (j['rating_strategy_name'] as String?) ?? 'value_v1',
        etfStrategyName:
            (j['etf_strategy_name'] as String?) ?? 'etf_rotation_kr',
        sleeveEtfWeight:
            ((j['sleeve_etf_weight'] as num?)?.toDouble() ?? 0.3).clamp(0.0, 1.0),
        toss: j['toss'] is Map ? TossSettings.fromJson(asJsonMap(j['toss'])) : null,
      );
}

/// Rounds a 0.0–1.0 ETF-sleeve weight into whole-percent (ETF, 주식) labels
/// for the settings slider. Shared by the UI and its tests so the rounding
/// rule (ETF rounds first, 주식 = 100 − ETF, never independently rounded)
/// stays in one place.
(int etfPct, int stockPct) sleeveWeightPct(double etfWeight) {
  final etf = (etfWeight.clamp(0.0, 1.0) * 100).round();
  return (etf, 100 - etf);
}

class KisAccountCreds {
  KisAccountCreds({
    required this.appKey,
    required this.appSecret,
    required this.accountNo,
  });

  final String appKey;
  final String appSecret;
  final String accountNo;

  Map<String, dynamic> toJson() => {
        'app_key': appKey,
        'app_secret': appSecret,
        'account_no': accountNo,
      };
}

class TossSettings {
  TossSettings({
    required this.hasCredentials,
    required this.clientIdMasked,
    this.accountSeq,
    required this.isMock,
    this.websocketSupported = false,
    this.specVersion = '1.1.1',
  });

  final bool hasCredentials;
  final String clientIdMasked;
  final int? accountSeq;
  final bool isMock;
  final bool websocketSupported;
  final String specVersion;

  factory TossSettings.fromJson(Map<String, dynamic> j) => TossSettings(
        hasCredentials: (j['has_credentials'] as bool?) ?? false,
        clientIdMasked: (j['client_id_masked'] as String?) ?? '',
        accountSeq: (j['account_seq'] as num?)?.toInt(),
        isMock: (j['is_mock'] as bool?) ?? true,
        websocketSupported: (j['websocket_supported'] as bool?) ?? false,
        specVersion: (j['spec_version'] as String?) ?? '1.1.1',
      );
}

class TossSettingsCreds {
  TossSettingsCreds({
    required this.clientId,
    required this.clientSecret,
    this.accountSeq,
    this.isMock = true,
  });

  final String clientId;
  final String clientSecret;
  final int? accountSeq;
  final bool isMock;

  Map<String, dynamic> toJson() => {
        'client_id': clientId,
        'client_secret': clientSecret,
        if (accountSeq != null) 'account_seq': accountSeq,
        'is_mock': isMock,
      };
}

class TestResult {
  TestResult({required this.ok, this.message, this.details});

  final bool ok;
  final String? message;
  final Map<String, dynamic>? details;

  factory TestResult.fromJson(Map<String, dynamic> j) => TestResult(
        ok: (j['ok'] as bool?) ?? false,
        message: j['message'] as String?,
        details: j['details'] is Map ? asJsonMap(j['details']) : null,
      );

  factory TestResult.error(String msg) => TestResult(ok: false, message: msg);
}

/// Result of a KOSPI200 universe refresh round-trip.
///
/// The backend distinguishes its data source via HTTP status:
///   - 200: official KRX (pykrx)
///   - 203: Non-Authoritative — Wikipedia fallback after official failed
///   - 206: approximate/cached/manual fallback
/// Inner body carries counts + diff so the UI can show what changed.
class UniverseRefreshOutcome {
  UniverseRefreshOutcome({required this.statusCode, required this.body});

  final int statusCode;
  final Map<String, dynamic> body;

  bool get isOfficial => statusCode == 200;
  bool get isWikipediaFallback => statusCode == 203;
  bool get isApproximateFallback => statusCode == 206;

  String? get source => body['source'] as String?;
  String? get message => body['message'] as String?;
  int? get currentCount => (body['current_count'] as num?)?.toInt();
  int? get previousCount => (body['previous_count'] as num?)?.toInt();
  List<String> get added =>
      ((body['added'] as List?) ?? const []).map((e) => e.toString()).toList();
  List<String> get removed =>
      ((body['removed'] as List?) ?? const []).map((e) => e.toString()).toList();
}

class SettingsApi {
  SettingsApi(this._ref);
  final Ref _ref;

  Future<AppSettings> getAll() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/settings');
    return AppSettings.fromJson(asJsonMap(res.data));
  }

  Future<void> patch(Map<String, dynamic> kv) async {
    final dio = _ref.read(dioProvider);
    await dio.patch<dynamic>('/api/settings', data: kv);
  }

  Future<void> updateAccount(KisAccount type, KisAccountCreds creds) async {
    final dio = _ref.read(dioProvider);
    await dio.post<dynamic>(
      '/api/settings/accounts/${type.wire}',
      data: creds.toJson(),
    );
  }

  Future<TestResult> testAccount(KisAccount type) async {
    final dio = _ref.read(dioProvider);
    try {
      final res = await dio.post<dynamic>('/api/settings/accounts/${type.wire}/test');
      return TestResult.fromJson(asJsonMap(res.data));
    } on ApiError catch (e) {
      return TestResult(ok: false, message: e.message, details: e.details);
    } catch (e) {
      return TestResult.error('$e');
    }
  }

  Future<void> saveTossSettings(TossSettingsCreds creds) async {
    final dio = _ref.read(dioProvider);
    await dio.post<dynamic>('/api/settings/toss', data: creds.toJson());
  }

  Future<TestResult> testToss() async {
    final dio = _ref.read(dioProvider);
    try {
      final res = await dio.post<dynamic>('/api/settings/toss/test');
      return TestResult.fromJson(asJsonMap(res.data));
    } on ApiError catch (e) {
      return TestResult(ok: false, message: e.message, details: e.details);
    } catch (e) {
      return TestResult.error('$e');
    }
  }

  /// Triggers a KOSPI200 universe re-sync on the backend. KRX scraping
  /// can take several seconds, so the per-call timeout is widened to 60s.
  Future<UniverseRefreshOutcome> refreshKospi200Universe() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/settings/universe/kospi200/refresh',
      options: Options(
        receiveTimeout: const Duration(seconds: 60),
        sendTimeout: const Duration(seconds: 60),
      ),
    );
    return UniverseRefreshOutcome(
      statusCode: res.statusCode ?? 0,
      body: asJsonMap(res.data),
    );
  }
}

final settingsApiProvider = Provider<SettingsApi>((ref) => SettingsApi(ref));
