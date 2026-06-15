/// File: app/lib/presentation/quant/builder/builder_controller.dart
///
/// Riverpod state for the Equation Builder screen.
/// Holds an editable [StrategyDefinitionDraft]; submitting calls the
/// backend `POST /api/backtest/run` and caches the full result in
/// [recentRunResultsProvider] for the detail screen to consume.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../data/api/backtest_api.dart';
import '../backtest_lab/backtest_lab_controller.dart';

/// Curated factor catalog. Backend treats factor as a plain string so
/// this list is the only client-side source of truth for the dropdown.
const kFactorCatalog = <FactorMeta>[
  FactorMeta('MOMENTUM_1M', '1M 모멘텀', '최근 1개월 수익률'),
  FactorMeta('MOMENTUM_3M', '3M 모멘텀', '최근 3개월 수익률'),
  FactorMeta('MOMENTUM_6M', '6M 모멘텀', '최근 6개월 수익률'),
  FactorMeta('MOMENTUM_12M', '12M 모멘텀', '최근 12개월 수익률'),
  FactorMeta('PER', 'PER', '주가수익비율 (역수 정렬)'),
  FactorMeta('PBR', 'PBR', '주가순자산비율 (역수 정렬)'),
  FactorMeta('PSR', 'PSR', '주가매출액비율 (역수 정렬)'),
  FactorMeta('ROE', 'ROE', '자기자본수익률'),
  FactorMeta('ROA', 'ROA', '총자산수익률'),
  FactorMeta('DIVIDEND_YIELD', '배당수익률', '연간 배당 ÷ 현재가'),
];

class FactorMeta {
  const FactorMeta(this.code, this.label, this.hint);
  final String code;
  final String label;
  final String hint;
}

const kFilterFields = <String>[
  'TRADING_DAYS_30D',
  'MARKET_CAP',
  'ADV_30D',
  'PER',
  'PBR',
  'DEBT_RATIO',
];

class BuilderState {
  BuilderState({required this.draft, this.busy = false, this.lastError, this.lastRunId});
  final StrategyDefinitionDraft draft;
  final bool busy;
  final String? lastError;
  final String? lastRunId;

  BuilderState copyWith({
    StrategyDefinitionDraft? draft,
    bool? busy,
    String? lastError,
    bool clearError = false,
    String? lastRunId,
  }) =>
      BuilderState(
        draft: draft ?? this.draft,
        busy: busy ?? this.busy,
        lastError: clearError ? null : (lastError ?? this.lastError),
        lastRunId: lastRunId ?? this.lastRunId,
      );

  /// Sum of all factor weights — UI uses this to nudge the user.
  double get weightSum => draft.factors.fold(0, (s, f) => s + f.weight);
  bool get isValid => draft.factors.isNotEmpty && draft.topN > 0;
}

class BuilderNotifier extends Notifier<BuilderState> {
  @override
  BuilderState build() => BuilderState(
        draft: StrategyDefinitionDraft(
          factors: [
            FactorWeightDraft(factor: 'MOMENTUM_1M', weight: 1.0),
          ],
        ),
      );

  void setName(String v) => state = state.copyWith(draft: state.draft.copyWith(name: v));
  void setDescription(String v) =>
      state = state.copyWith(draft: state.draft.copyWith(description: v));
  void setUniverse(BacktestUniverse v) =>
      state = state.copyWith(draft: state.draft.copyWith(universe: v));
  void setRebalance(BacktestRebalanceFreq v) =>
      state = state.copyWith(draft: state.draft.copyWith(rebalanceFreq: v));
  void setTopN(int v) => state = state.copyWith(draft: state.draft.copyWith(topN: v));
  void setStartDate(DateTime d) =>
      state = state.copyWith(draft: state.draft.copyWith(startDate: d));
  void setEndDate(DateTime d) =>
      state = state.copyWith(draft: state.draft.copyWith(endDate: d));

  // ----- factors -----------------------------------------------------------

  /// True when every entry in [kFactorCatalog] is already in the draft —
  /// guards the [+ Add Factor] button so users can't insert duplicates.
  bool get catalogExhausted {
    final used = state.draft.factors.map((f) => f.factor).toSet();
    return kFactorCatalog.every((f) => used.contains(f.code));
  }

  void addFactor() {
    final used = state.draft.factors.map((f) => f.factor).toSet();
    if (used.length >= kFactorCatalog.length) {
      // All catalog entries already used; silently no-op. The button
      // should be disabled via `catalogExhausted` so this path is rare.
      return;
    }
    final next = kFactorCatalog.firstWhere((f) => !used.contains(f.code));
    state = state.copyWith(
      draft: state.draft.copyWith(factors: [
        ...state.draft.factors,
        FactorWeightDraft(factor: next.code, weight: 0.5),
      ]),
    );
  }

  void removeFactor(int idx) {
    final list = [...state.draft.factors]..removeAt(idx);
    state = state.copyWith(draft: state.draft.copyWith(factors: list));
  }

  void updateFactor(int idx, FactorWeightDraft v) {
    final list = [...state.draft.factors];
    list[idx] = v;
    state = state.copyWith(draft: state.draft.copyWith(factors: list));
  }

  /// Normalize all weights so they sum to 1.0.
  void normalizeWeights() {
    if (state.draft.factors.isEmpty) return;
    final sum = state.weightSum;
    if (sum <= 0) return;
    final list = [
      for (final f in state.draft.factors)
        FactorWeightDraft(factor: f.factor, weight: f.weight / sum, transform: f.transform),
    ];
    state = state.copyWith(draft: state.draft.copyWith(factors: list));
  }

  // ----- filters -----------------------------------------------------------
  void addFilter() {
    state = state.copyWith(
      draft: state.draft.copyWith(filters: [
        ...state.draft.filters,
        FilterRuleDraft(field: 'TRADING_DAYS_30D', op: BacktestFilterOp.gte, value: 15.0),
      ]),
    );
  }

  void removeFilter(int idx) {
    final list = [...state.draft.filters]..removeAt(idx);
    state = state.copyWith(draft: state.draft.copyWith(filters: list));
  }

  void updateFilter(int idx, FilterRuleDraft v) {
    final list = [...state.draft.filters];
    list[idx] = v;
    state = state.copyWith(draft: state.draft.copyWith(filters: list));
  }

  // ----- submit ------------------------------------------------------------
  Future<BacktestRunResult?> run() async {
    if (state.busy) return null;
    state = state.copyWith(busy: true, clearError: true);
    try {
      final result = await ref.read(backtestApiProvider).runBacktest(state.draft);
      // Cache in the recent-runs map so the detail screen can read equity_curve.
      final cache = ref.read(recentRunResultsProvider);
      ref.read(recentRunResultsProvider.notifier).state = {
        ...cache,
        result.runId: result,
      };
      // Invalidate the leaderboard so the new run appears.
      ref.invalidate(backtestRunsProvider);
      state = state.copyWith(busy: false, lastRunId: result.runId, clearError: true);
      return result;
    } catch (e) {
      state = state.copyWith(busy: false, lastError: '$e');
      return null;
    }
  }
}

final builderProvider =
    NotifierProvider<BuilderNotifier, BuilderState>(BuilderNotifier.new);
