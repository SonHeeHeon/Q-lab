/// File: app/lib/data/api/ratings_api.dart
///
/// Dio wrapper for `/api/ratings*` — logic-based (non-LLM) buy/sell rating
/// axes (PROJECT_BLUEPRINT.md §4.4, `backend/app/services/ratings/`).
/// Backend ref: `backend/app/services/ratings/buy_axis.py` (5-tier buy
/// grade from strategy-universe percentile) and `sell_axis.py` (5-tier
/// sell grade from stop-loss/take-profit/score-percentile/band-trim
/// rules, in that priority order).
///
/// Display-only: ratings never place orders directly (see T6 task scope);
/// they feed `RatingChip` (shared/widgets/rating_chip.dart) and the
/// approval-based proposal pipeline (`proposals_api.dart`) separately.
library;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../parse_utils.dart';
import 'api_client.dart';

/// Buy-axis rating for one stock code (`GET /api/ratings`,
/// `POST /api/ratings/compute`).
class StockRating {
  StockRating({
    required this.code,
    required this.status,
    required this.buyGrade,
    required this.score,
    required this.percentile,
    required this.weakestGroup,
    required this.strategyName,
    required this.asOf,
    required this.updatedAt,
  });

  final String code;

  /// 'OK' | 'NO_DATA' | 'UNSUPPORTED' (e.g. a US ticker on the KR-only
  /// buy-axis universe).
  final String status;

  /// STRONG_BUY/BUY/NEUTRAL/REDUCE/AVOID — null unless [status] is 'OK'.
  final String? buyGrade;
  final double? score;

  /// 1.0 = best, relative to the strategy universe distribution.
  final double? percentile;
  final String? weakestGroup;
  final String strategyName;
  final String asOf;
  final String updatedAt;

  factory StockRating.fromJson(Map<String, dynamic> j) => StockRating(
        code: j['code']?.toString() ?? '',
        status: j['status']?.toString() ?? 'NO_DATA',
        buyGrade: j['buy_grade'] as String?,
        score: safeDoubleOrNull(j['score'], hint: 'rating.score'),
        percentile:
            safeDoubleOrNull(j['percentile'], hint: 'rating.percentile'),
        weakestGroup: j['weakest_group'] as String?,
        strategyName: j['strategy_name']?.toString() ?? '',
        asOf: j['as_of']?.toString() ?? '',
        updatedAt: j['updated_at']?.toString() ?? '',
      );
}

/// Sell-axis rating for one held position (`GET /api/ratings/positions`).
/// Keyed by (broker, account_key, code) since the same code can be held in
/// multiple accounts.
class PositionRating {
  PositionRating({
    required this.broker,
    required this.accountKey,
    required this.code,
    required this.sellGrade,
    required this.reason,
    required this.plRate,
    required this.lane,
    required this.updatedAt,
  });

  final String broker;
  final String accountKey;
  final String code;

  /// SELL_NOW/SELL/WATCH/HOLD/KEEP — severity descends in that order
  /// (SELL_NOW is most urgent; see `sell_axis.py` module docstring).
  final String sellGrade;

  /// Structured rule metadata, e.g. `{"rule": "STOP_LOSS", "pl_rate": -12.3,
  /// "threshold": -10.0}` — drives [RatingChip]'s tooltip via `reasonText`.
  final Map<String, dynamic> reason;

  /// Broker unrealized P/L rate in percent (e.g. `-12.3` = -12.3%).
  final double? plRate;

  /// 'EOD' | 'INTRADAY' — which scheduler pass produced this rating.
  final String lane;
  final String updatedAt;

  factory PositionRating.fromJson(Map<String, dynamic> j) => PositionRating(
        broker: j['broker']?.toString() ?? '',
        accountKey: j['account_key']?.toString() ?? '',
        code: j['code']?.toString() ?? '',
        sellGrade: j['sell_grade']?.toString() ?? 'HOLD',
        reason:
            j['reason'] is Map ? asJsonMap(j['reason']) : <String, dynamic>{},
        plRate: safeDoubleOrNull(j['pl_rate'], hint: 'rating.pl_rate'),
        lane: j['lane']?.toString() ?? 'EOD',
        updatedAt: j['updated_at']?.toString() ?? '',
      );
}

/// EOD (end-of-day) batch completion marker within [RatingStatus].
class RatingEodStatus {
  RatingEodStatus({
    required this.finishedAt,
    required this.asOf,
    required this.storedCount,
  });

  final String finishedAt;
  final String asOf;
  final int storedCount;

  factory RatingEodStatus.fromJson(Map<String, dynamic> j) => RatingEodStatus(
        finishedAt: j['finished_at']?.toString() ?? '',
        asOf: j['as_of']?.toString() ?? '',
        storedCount: safeInt(j['stored_count'], hint: 'rating.stored_count'),
      );
}

/// Intraday batch completion marker within [RatingStatus].
class RatingIntradayStatus {
  RatingIntradayStatus({required this.finishedAt});

  final String finishedAt;

  factory RatingIntradayStatus.fromJson(Map<String, dynamic> j) =>
      RatingIntradayStatus(finishedAt: j['finished_at']?.toString() ?? '');
}

/// `GET /api/ratings/status` — scheduler health for the "오늘의 평가"
/// freshness indicator.
class RatingStatus {
  RatingStatus({
    required this.eod,
    required this.intraday,
    required this.schedulerRunning,
    required this.strategyName,
  });

  final RatingEodStatus? eod;
  final RatingIntradayStatus? intraday;
  final bool schedulerRunning;
  final String strategyName;

  factory RatingStatus.fromJson(Map<String, dynamic> j) => RatingStatus(
        eod: j['eod'] is Map
            ? RatingEodStatus.fromJson(asJsonMap(j['eod']))
            : null,
        intraday: j['intraday'] is Map
            ? RatingIntradayStatus.fromJson(asJsonMap(j['intraday']))
            : null,
        schedulerRunning: j['scheduler_running'] == true,
        strategyName: j['strategy_name']?.toString() ?? '',
      );
}

class RatingsApi {
  RatingsApi(this._ref);
  final Ref _ref;

  /// Batch buy-axis lookup. Returns `[]` for an empty [codes] list without
  /// a round trip (avoids sending a valueless `codes=` query param).
  Future<List<StockRating>> getRatings(List<String> codes) async {
    if (codes.isEmpty) return const [];
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/ratings',
      queryParameters: {'codes': codes.join(',')},
    );
    final list = (res.data as List?) ?? const [];
    return list.map((e) => StockRating.fromJson(asJsonMap(e))).toList();
  }

  /// Sell-axis ratings for every position across all linked accounts.
  Future<List<PositionRating>> getPositions() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/ratings/positions');
    final list = (res.data as List?) ?? const [];
    return list.map((e) => PositionRating.fromJson(asJsonMap(e))).toList();
  }

  /// On-demand single-code compute (e.g. from the stock detail screen for
  /// a code outside the last scheduled batch). Can take 5-15s — UNSUPPORTED
  /// (non-KR tickers) returns quickly, but a cold-cache KR compute does not
  /// — so the per-call timeout is widened well past the shared client's
  /// 12s default.
  Future<StockRating> computeRating(String code) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/ratings/compute',
      queryParameters: {'code': code},
      options: Options(
        receiveTimeout: const Duration(seconds: 20),
        sendTimeout: const Duration(seconds: 20),
      ),
    );
    return StockRating.fromJson(asJsonMap(res.data));
  }

  Future<RatingStatus> getStatus() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/ratings/status');
    return RatingStatus.fromJson(asJsonMap(res.data));
  }
}

final ratingsApiProvider = Provider<RatingsApi>((ref) => RatingsApi(ref));

/// Deterministic family key for [ratingsMapProvider]: sorts + dedupes so the
/// same code set always resolves to the same cached provider instance
/// regardless of caller-side ordering (e.g. a search screen and a watchlist
/// screen both requesting the same codes share one in-flight fetch).
String ratingsKey(Iterable<String> codes) =>
    (codes.toSet().toList()..sort()).join(',');

/// Batch buy ratings keyed by code, for screens that need to join a rating
/// onto a list of stocks (search results, watchlist, portfolio rows).
/// Family key must be built with [ratingsKey] — screens can then
/// `ref.watch(ratingsMapProvider(key).select((v) => v.valueOrNull?[code]))`
/// to rebuild only when that one code's rating actually changes.
final ratingsMapProvider =
    FutureProvider.family<Map<String, StockRating>, String>(
        (ref, codesKey) async {
  final codes = codesKey.split(',').where((c) => c.isNotEmpty).toList();
  if (codes.isEmpty) return const {};
  final list = await ref.read(ratingsApiProvider).getRatings(codes);
  return {for (final r in list) r.code: r};
});
