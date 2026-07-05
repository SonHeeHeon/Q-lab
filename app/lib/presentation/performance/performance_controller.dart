/// File: app/lib/presentation/performance/performance_controller.dart
///
/// Riverpod state for the 성과 분석 (Performance Analysis) screen — compares
/// a single strategy across BACKTEST / PAPER / REAL modes.
///
/// Data sourcing:
///   - BACKTEST: adapted client-side from the already-working
///     `backtestApiProvider` (`GET /api/backtest/runs` + `/runs/{id}`).
///     NOTE: those endpoints return metrics + params only, never the
///     equity_curve — a curve is only available when the user ran that
///     exact run in-session via the Builder, cached in
///     `recentRunResultsProvider` (see backtest_lab_controller.dart).
///   - PAPER / REAL: `performanceApiProvider.paper()` / `.real()` — NEW
///     endpoints, not yet built by the backend (404 today).
///   - Comparison (headline): prefers `performanceApiProvider.compare()`;
///     on 404 falls back to fanning out to the three sources above so the
///     centerpiece still shows whatever already works (today: backtest
///     only) instead of blocking on the unbuilt endpoint.
library;

import 'dart:math' show pow;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/api_client.dart';
import '../../data/api/backtest_api.dart';
import '../../data/api/performance_api.dart';
import '../quant/backtest_lab/backtest_lab_controller.dart' show recentRunResultsProvider;

/// TODO(lead): replace with a real strategy registry endpoint (e.g.
/// `GET /api/strategies`) once one exists. For now this mirrors the
/// strategy names available in the Equation Builder / Backtest Lab.
const kPerformanceStrategies = <String>['value_v1', 'qlab_alpha_v2'];

final selectedPerformanceStrategyProvider =
    StateProvider<String>((ref) => kPerformanceStrategies.first);

/// Which per-mode detail section is expanded below the comparison headline.
enum PerfDetailMode { backtest, paper, real }

final performanceDetailModeProvider =
    StateProvider<PerfDetailMode>((ref) => PerfDetailMode.backtest);

// ---------------------------------------------------------------------------
// BACKTEST — adapted from the existing, already-working backtest APIs.
// ---------------------------------------------------------------------------

/// All runs for the selected strategy, most-recent first. Empty when the
/// strategy has never been backtested.
final backtestRunsForStrategyProvider = FutureProvider<List<BacktestRunSummary>>((ref) async {
  final strategy = ref.watch(selectedPerformanceStrategyProvider);
  final all = await ref.read(backtestApiProvider).listRuns();
  final filtered = all.where((r) => r.strategy == strategy).toList()
    ..sort((a, b) => b.runId.compareTo(a.runId));
  return filtered;
});

/// The BACKTEST side of the comparison — `null` when no run exists yet for
/// the selected strategy (screen shows an empty state guiding to the
/// Builder in that case).
final backtestPerfProvider = FutureProvider<PerfModeResult?>((ref) async {
  final runs = await ref.watch(backtestRunsForStrategyProvider.future);
  if (runs.isEmpty) return null;

  final latest = runs.first;
  final detail = await ref.read(backtestApiProvider).getRun(latest.runId);
  final cached = ref.watch(recentRunResultsProvider)[latest.runId];

  final curve = cached?.equityCurve
          .map((e) => PerfSeriesPoint(date: e.date, nav: e.nav))
          .toList() ??
      const <PerfSeriesPoint>[];

  return PerfModeResult(
    mode: 'BACKTEST',
    equityCurve: curve,
    metrics: _perfMetricsFromBacktest(detail.metrics, latest),
    asOf: latest.endDate,
    startDate: latest.startDate,
    initialNav: cached?.initialNav,
    currentNav: latest.finalNav,
  );
});

/// CAGR is, by definition, the annualized form of the run's total return —
/// `total_return = (1 + cagr) ^ years - 1`. That means total_return can be
/// reconstructed *exactly* from CAGR + the run's own duration even without
/// the underlying equity curve (which the list/detail endpoints don't
/// return — see the [backtestPerfProvider] doc comment above), instead of
/// guessing at an initial-capital assumption.
PerfMetrics _perfMetricsFromBacktest(BacktestMetrics m, BacktestRunSummary run) {
  final years = run.endDate.difference(run.startDate).inDays / 365.25;
  final totalReturn = years > 0 ? pow(1 + m.cagr, years).toDouble() - 1 : m.cagr;
  return PerfMetrics(
    cagr: m.cagr,
    mdd: m.mdd,
    sharpe: m.sharpe,
    winRate: m.winRate,
    totalReturn: totalReturn,
    sortino: m.sortino,
    nTrades: m.nTrades,
    avgHoldingDays: m.avgHoldingDays,
    turnover: m.turnover,
  );
}

// ---------------------------------------------------------------------------
// PAPER / REAL — new endpoints, not yet built (404 today).
// ---------------------------------------------------------------------------

/// Left un-caught here on purpose: the screen's per-mode detail tabs need
/// to distinguish "backend missing" (404) from a real error to show the
/// right message, so they inspect the thrown [ApiError] themselves —
/// mirroring `presentation/home/home_controller.dart`.
final paperPerfProvider = FutureProvider<PerfModeResult>((ref) async {
  final strategy = ref.watch(selectedPerformanceStrategyProvider);
  return ref.read(performanceApiProvider).paper(strategy);
});

final realPerfProvider = FutureProvider<PerfModeResult>((ref) async {
  final strategy = ref.watch(selectedPerformanceStrategyProvider);
  return ref.read(performanceApiProvider).real(strategy);
});

// ---------------------------------------------------------------------------
// Comparison (headline) — self-healing: upgrades to the unified endpoint
// transparently once it exists.
// ---------------------------------------------------------------------------

final performanceComparisonProvider = FutureProvider<PerfComparison>((ref) async {
  final strategy = ref.watch(selectedPerformanceStrategyProvider);
  final api = ref.read(performanceApiProvider);

  try {
    return await api.compare(strategy);
  } on ApiError catch (e) {
    if (e.statusCode != 404) rethrow;
  }

  // `/api/performance/compare` isn't built yet — fan out to whichever
  // sources already work instead of blocking the whole centerpiece on one
  // unbuilt route. `backtestPerfProvider` never 404s (it's not backed by
  // an HTTP call), so a real failure there should still surface.
  final backtest = await ref.watch(backtestPerfProvider.future);
  final paper = await _perfOrNull(() => api.paper(strategy));
  final real = await _perfOrNull(() => api.real(strategy));
  return PerfComparison(backtest: backtest, paper: paper, real: real);
});

Future<PerfModeResult?> _perfOrNull(Future<PerfModeResult> Function() fetch) async {
  try {
    return await fetch();
  } on ApiError catch (e) {
    if (e.statusCode == 404) return null;
    rethrow;
  }
}
