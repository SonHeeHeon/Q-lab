/// File: app/lib/presentation/quant/backtest_lab/portfolio_run_controller.dart
///
/// Riverpod state for the multi-sleeve portfolio backtest form
/// (Backtest Lab, T-P3). Holds an editable list of [SleeveDraft] rows;
/// submitting calls `POST /api/backtest/run-portfolio` and keeps the
/// result in-state for the run screen's result view (no separate cache
/// needed — unlike the single-run builder, this screen renders its own
/// result inline rather than navigating to a detail screen).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../data/api/backtest_api.dart';

/// Floor/ceiling for the sleeve picker. The floor keeps this screen
/// meaningfully "multi" (a single sleeve is just the equation builder);
/// the ceiling keeps the sleeve-identity color palette
/// (`portfolio_run_screen.dart`'s `_sleeveColors`) collision-free — every
/// index up to the max maps to a distinct color.
const kMinSleeves = 2;
const kMaxSleeves = 6;

/// One editable sleeve row: a chosen strategy preset name (empty = not yet
/// chosen) plus its raw slider weight (not required to sum to 1.0 across
/// rows — see [normalizeSleeveWeights]).
class SleeveDraft {
  SleeveDraft({required this.strategyName, required this.weight});
  final String strategyName;
  final double weight;

  SleeveDraft copyWith({String? strategyName, double? weight}) => SleeveDraft(
        strategyName: strategyName ?? this.strategyName,
        weight: weight ?? this.weight,
      );
}

class PortfolioRunState {
  PortfolioRunState({
    required this.sleeves,
    this.rebalance = BacktestRebalanceFreq.quarterly,
    this.afterTax = false,
    this.optimize = false,
    this.oos = false,
    this.busy = false,
    this.lastError,
    this.result,
  });

  final List<SleeveDraft> sleeves;
  final BacktestRebalanceFreq rebalance;
  final bool afterTax;
  final bool optimize;

  /// OOS validation of the optimizer — only meaningful (and only sent to
  /// the backend) when [optimize] is also true; see [PortfolioRunNotifier.run].
  final bool oos;

  final bool busy;
  final String? lastError;
  final PortfolioRunResult? result;

  double get weightSum => sleeves.fold(0.0, (s, x) => s + x.weight);

  /// Whether the current slider values already sum to ~100% — drives the
  /// sum indicator's color (green vs amber) in the sleeve picker header.
  /// Purely a visual hint: [run] auto-normalizes regardless, so an
  /// imperfect sum here never blocks submission.
  bool get weightSumValid => (weightSum - 1.0).abs() < 0.01;

  /// Every row needs a chosen strategy and at least one row needs a
  /// positive weight (an all-zero blend can't be normalized) before the
  /// run button is enabled.
  bool get isValid =>
      sleeves.length >= kMinSleeves &&
      sleeves.every((s) => s.strategyName.isNotEmpty) &&
      weightSum > 0;

  PortfolioRunState copyWith({
    List<SleeveDraft>? sleeves,
    BacktestRebalanceFreq? rebalance,
    bool? afterTax,
    bool? optimize,
    bool? oos,
    bool? busy,
    String? lastError,
    bool clearError = false,
    PortfolioRunResult? result,
    bool clearResult = false,
  }) =>
      PortfolioRunState(
        sleeves: sleeves ?? this.sleeves,
        rebalance: rebalance ?? this.rebalance,
        afterTax: afterTax ?? this.afterTax,
        optimize: optimize ?? this.optimize,
        oos: oos ?? this.oos,
        busy: busy ?? this.busy,
        lastError: clearError ? null : (lastError ?? this.lastError),
        result: clearResult ? null : (result ?? this.result),
      );
}

class PortfolioRunNotifier extends Notifier<PortfolioRunState> {
  @override
  PortfolioRunState build() => PortfolioRunState(
        sleeves: [
          SleeveDraft(strategyName: '', weight: 0.5),
          SleeveDraft(strategyName: '', weight: 0.5),
        ],
      );

  void addSleeve() {
    if (state.sleeves.length >= kMaxSleeves) return;
    state = state.copyWith(
      sleeves: [...state.sleeves, SleeveDraft(strategyName: '', weight: 0.0)],
      clearResult: true,
    );
  }

  void removeSleeve(int idx) {
    if (state.sleeves.length <= kMinSleeves) return;
    final list = [...state.sleeves]..removeAt(idx);
    state = state.copyWith(sleeves: list, clearResult: true);
  }

  void setStrategyName(int idx, String name) {
    final list = [...state.sleeves];
    list[idx] = list[idx].copyWith(strategyName: name);
    state = state.copyWith(sleeves: list, clearResult: true);
  }

  void setWeight(int idx, double weight) {
    final list = [...state.sleeves];
    list[idx] = list[idx].copyWith(weight: weight);
    state = state.copyWith(sleeves: list, clearResult: true);
  }

  /// "정규화" affordance — rescales every row so the sum reads exactly
  /// 100% without changing the relative blend. A no-op while every row is
  /// still at weight 0 (nothing to rescale).
  void normalizeWeights() {
    final weights = normalizeSleeveWeights([for (final s in state.sleeves) s.weight]);
    final list = [
      for (var i = 0; i < state.sleeves.length; i++) state.sleeves[i].copyWith(weight: weights[i]),
    ];
    state = state.copyWith(sleeves: list);
  }

  void setRebalance(BacktestRebalanceFreq v) => state = state.copyWith(rebalance: v, clearResult: true);
  void setAfterTax(bool v) => state = state.copyWith(afterTax: v, clearResult: true);

  /// Turning `optimize` off also clears `oos` — OOS validation only ever
  /// makes sense as a follow-up to a weight search.
  void setOptimize(bool v) =>
      state = state.copyWith(optimize: v, oos: v ? state.oos : false, clearResult: true);
  void setOos(bool v) => state = state.copyWith(oos: v, clearResult: true);

  Future<void> run() async {
    if (state.busy || !state.isValid) return;
    state = state.copyWith(busy: true, clearError: true);
    try {
      final api = ref.read(backtestApiProvider);
      // Auto-normalize on run rather than block submission on an imperfect
      // slider sum — the backend expects blend weights that sum to 1.0,
      // and requiring a manual "정규화" tap before every run would be
      // friction for the common "just eyeball the sliders" case. The sum
      // indicator (`weightSumValid`) still warns before this point.
      final normalized = normalizeSleeveWeights([for (final s in state.sleeves) s.weight]);
      final sleeveReqs = [
        for (var i = 0; i < state.sleeves.length; i++)
          PortfolioSleeveRequest(strategyName: state.sleeves[i].strategyName, weight: normalized[i]),
      ];
      final result = await api.runPortfolio(
        sleeves: sleeveReqs,
        rebalance: state.rebalance,
        optimize: state.optimize,
        oos: state.optimize && state.oos,
        afterTax: state.afterTax,
      );
      state = state.copyWith(busy: false, result: result, clearError: true);
      ref.invalidate(portfolioListProvider);
    } catch (e) {
      state = state.copyWith(busy: false, lastError: '$e');
    }
  }
}

final portfolioRunProvider =
    NotifierProvider<PortfolioRunNotifier, PortfolioRunState>(PortfolioRunNotifier.new);
