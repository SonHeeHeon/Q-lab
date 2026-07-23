/// File: app/lib/presentation/quant/backtest_lab/backtest_lab_controller.dart
///
/// Riverpod state for the Backtest Lab — list view + detail fetch.
/// Equation-builder state will land in a later phase.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../data/api/backtest_api.dart';

enum RunSortBy { date, cagr, sharpe, mdd, winRate }

final runSortByProvider = StateProvider<RunSortBy>((ref) => RunSortBy.date);

/// Model filter for the runs list — `null` means 전체 (no filter, every
/// model shown). Purely client-side: `backtestRunsProvider` already fetches
/// every run, so flipping this provider only changes what
/// `BacktestLabScreen` renders — no refetch.
final runModelFilterProvider = StateProvider<String?>((ref) => null);

/// Parses the human-readable execution timestamp out of a `run_id` of the
/// form `YYYYMMDD_HHMMSS_<slug>` (the backend's backtest run-id
/// convention). Returns `null` when the id doesn't match that shape so
/// callers can fall back to showing the raw run_id instead.
DateTime? runTimestampFromId(String runId) {
  final parts = runId.split('_');
  if (parts.length < 2) return null;
  final datePart = parts[0];
  final timePart = parts[1];
  if (datePart.length != 8 || timePart.length < 4) return null;
  final y = int.tryParse(datePart.substring(0, 4));
  final mo = int.tryParse(datePart.substring(4, 6));
  final d = int.tryParse(datePart.substring(6, 8));
  final hh = int.tryParse(timePart.substring(0, 2));
  final mm = int.tryParse(timePart.substring(2, 4));
  if (y == null || mo == null || d == null || hh == null || mm == null) {
    return null;
  }
  try {
    return DateTime(y, mo, d, hh, mm);
  } on ArgumentError {
    return null;
  }
}

final backtestRunsProvider = FutureProvider<List<BacktestRunSummary>>((ref) async {
  final list = await ref.read(backtestApiProvider).listRuns();
  final sortBy = ref.watch(runSortByProvider);
  final sorted = [...list];
  switch (sortBy) {
    case RunSortBy.date:
      sorted.sort((a, b) => b.runId.compareTo(a.runId));
      break;
    case RunSortBy.cagr:
      sorted.sort((a, b) => b.cagr.compareTo(a.cagr));
      break;
    case RunSortBy.sharpe:
      sorted.sort((a, b) => b.sharpe.compareTo(a.sharpe));
      break;
    case RunSortBy.mdd:
      sorted.sort((a, b) => b.mdd.compareTo(a.mdd)); // less negative is better
      break;
    case RunSortBy.winRate:
      sorted.sort((a, b) => b.winRate.compareTo(a.winRate));
      break;
  }
  return sorted;
});

final backtestRunDetailProvider =
    FutureProvider.family<BacktestRunDetail, String>((ref, runId) {
  return ref.read(backtestApiProvider).getRun(runId);
});

/// In-memory cache of full run results returned by POST /api/backtest/run
/// during this session. The GET detail endpoint does NOT include the
/// equity_curve, so this cache is the only way the detail screen can show
/// the line chart for runs the user just executed.
///
/// Keyed by `run_id`. Reset on app reload.
final recentRunResultsProvider =
    StateProvider<Map<String, BacktestRunResult>>((ref) => const {});
