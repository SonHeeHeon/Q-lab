/// File: app/lib/data/api/performance_api.dart
///
/// Dio wrapper for `/api/performance*` — cross-mode performance comparison
/// (BACKTEST vs PAPER vs REAL) for a given quant strategy.
///
/// Backend status: `/api/performance/paper`, `/api/performance/real`, and
/// `/api/performance/compare` are NEW endpoints that do not exist yet —
/// calls will 404 until the backend (Codex) ships them. Callers MUST catch
/// [ApiError] and check `statusCode == 404` to distinguish "feature not
/// built yet" from a real failure — see
/// `presentation/home/home_controller.dart` for the established pattern,
/// mirrored by `presentation/performance/performance_controller.dart`.
///
/// The BACKTEST mode does NOT use any endpoint in this file — it's adapted
/// client-side from the already-working `backtestApiProvider`
/// (see performance_controller.dart).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../parse_utils.dart';
import 'api_client.dart';

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

/// One point on an equity curve.
class PerfSeriesPoint {
  PerfSeriesPoint({required this.date, required this.nav});

  final DateTime date;
  final double nav;

  factory PerfSeriesPoint.fromJson(Map<String, dynamic> j) => PerfSeriesPoint(
        date: DateTime.parse(j['date'] as String),
        nav: _d(j['nav']),
      );
}

/// Headline metrics for a single mode.
///
/// [cagr] / [mdd] / [sharpe] / [winRate] / [totalReturn] are the 5 metrics
/// shown in the comparison table and are always present per the API
/// contract. The remaining fields are optional extras — not shown in the
/// comparison table, but surfaced in the per-mode detail metrics grid when
/// available. They also mirror [BacktestMetrics] so a backtest run can be
/// losslessly adapted into a [PerfMetrics] (see performance_controller.dart).
class PerfMetrics {
  PerfMetrics({
    required this.cagr,
    required this.mdd,
    required this.sharpe,
    required this.winRate,
    required this.totalReturn,
    this.sortino,
    this.nTrades,
    this.avgHoldingDays,
    this.turnover,
  });

  final double cagr;
  final double mdd;
  final double sharpe;
  final double winRate;
  final double totalReturn;

  final double? sortino;
  final int? nTrades;
  final double? avgHoldingDays;
  final double? turnover;

  factory PerfMetrics.fromJson(Map<String, dynamic> j) => PerfMetrics(
        cagr: _d(j['cagr']),
        mdd: _d(j['mdd']),
        sharpe: _d(j['sharpe']),
        winRate: _d(j['win_rate']),
        totalReturn: _d(j['total_return']),
        sortino: safeDoubleOrNull(j['sortino'], hint: 'performance.sortino'),
        // No safeIntOrNull helper exists in parse_utils — round a
        // safeDoubleOrNull instead so a Decimal-as-string payload (or a
        // missing field) is handled the same defensive way as everywhere
        // else in this file.
        nTrades: safeDoubleOrNull(j['n_trades'], hint: 'performance.n_trades')?.round(),
        avgHoldingDays: safeDoubleOrNull(j['avg_holding_days'], hint: 'performance.avg_holding_days'),
        turnover: safeDoubleOrNull(j['turnover'], hint: 'performance.turnover'),
      );
}

/// Full result for one mode (BACKTEST / PAPER / REAL).
class PerfModeResult {
  PerfModeResult({
    required this.mode,
    required this.equityCurve,
    required this.metrics,
    this.benchmarkCurve,
    this.asOf,
    this.initialNav,
    this.currentNav,
    this.accountType,
    this.startDate,
  });

  /// 'BACKTEST' | 'PAPER' | 'REAL'.
  final String mode;
  final List<PerfSeriesPoint> equityCurve;
  final List<PerfSeriesPoint>? benchmarkCurve;
  final PerfMetrics metrics;
  final DateTime? asOf;
  final double? initialNav;
  final double? currentNav;

  /// 'PAPER' | 'REAL' | 'ISA' — only ever populated by the `real` endpoint
  /// per the API contract, since a 실전 strategy could in principle run
  /// against more than one KIS account type.
  final String? accountType;
  final DateTime? startDate;

  /// [modeHint] fills in [mode] when the payload doesn't carry its own —
  /// e.g. the nested objects inside `/api/performance/compare`, whose
  /// documented shape is just `{equity_curve, metrics}` with no `mode` key.
  factory PerfModeResult.fromJson(Map<String, dynamic> j, {String? modeHint}) {
    final curve = ((j['equity_curve'] as List?) ?? const [])
        .map((e) => PerfSeriesPoint.fromJson(asJsonMap(e)))
        .toList();
    final benchmark = j['benchmark_curve'] as List?;
    return PerfModeResult(
      mode: (j['mode'] as String?) ?? modeHint ?? '',
      equityCurve: curve,
      benchmarkCurve: benchmark?.map((e) => PerfSeriesPoint.fromJson(asJsonMap(e))).toList(),
      metrics: PerfMetrics.fromJson(asJsonMap(j['metrics'])),
      asOf: j['as_of'] == null ? null : DateTime.tryParse(j['as_of'] as String),
      initialNav: safeDoubleOrNull(j['initial_nav'], hint: 'performance.initial_nav'),
      currentNav: safeDoubleOrNull(j['current_nav'], hint: 'performance.current_nav'),
      accountType: j['account_type'] as String?,
      startDate: j['start_date'] == null ? null : DateTime.tryParse(j['start_date'] as String),
    );
  }
}

/// `/api/performance/compare` response: up to 3 modes side by side. Any of
/// the three may be `null` — either the backend genuinely has no data yet
/// for that mode (e.g. no real-money trades logged) or (today) the whole
/// endpoint hasn't shipped, in which case
/// `performance_controller.dart`'s comparison provider fans out to the
/// individually-available sources instead.
class PerfComparison {
  PerfComparison({this.backtest, this.paper, this.real});

  final PerfModeResult? backtest;
  final PerfModeResult? paper;
  final PerfModeResult? real;

  factory PerfComparison.fromJson(Map<String, dynamic> j) => PerfComparison(
        backtest: j['backtest'] == null
            ? null
            : PerfModeResult.fromJson(asJsonMap(j['backtest']), modeHint: 'BACKTEST'),
        paper: j['paper'] == null
            ? null
            : PerfModeResult.fromJson(asJsonMap(j['paper']), modeHint: 'PAPER'),
        real: j['real'] == null
            ? null
            : PerfModeResult.fromJson(asJsonMap(j['real']), modeHint: 'REAL'),
      );
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

class PerformanceApi {
  PerformanceApi(this._ref);
  final Ref _ref;

  Future<PerfModeResult> paper(String strategy) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/performance/paper',
      queryParameters: {'strategy': strategy},
    );
    return PerfModeResult.fromJson(asJsonMap(res.data), modeHint: 'PAPER');
  }

  Future<PerfModeResult> real(String strategy) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/performance/real',
      queryParameters: {'strategy': strategy},
    );
    return PerfModeResult.fromJson(asJsonMap(res.data), modeHint: 'REAL');
  }

  /// The "money endpoint" — backtest + paper + real in one call. Preferred
  /// by [performance_controller.dart]'s comparison provider when available;
  /// on 404 that provider falls back to fanning out to [paper] / [real] /
  /// `backtestApiProvider` individually.
  Future<PerfComparison> compare(String strategy) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/performance/compare',
      queryParameters: {'strategy': strategy},
    );
    return PerfComparison.fromJson(asJsonMap(res.data));
  }
}

final performanceApiProvider = Provider<PerformanceApi>((ref) => PerformanceApi(ref));

double _d(Object? v) => safeDouble(v, hint: 'performance');
