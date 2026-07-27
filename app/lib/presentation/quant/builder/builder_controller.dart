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
/// 엔진(_factor_series)이 실제 계산하는 팩터만 노출 — 미구현 팩터는 조용히
/// 빈 값이 되어 방정식을 오염시킨다 (PSR/DIVIDEND_YIELD 제거 사유).
const kFactorCatalog = <FactorMeta>[
  FactorMeta('MOMENTUM_1M', '1M 모멘텀', '최근 1개월 수익률'),
  FactorMeta('MOMENTUM_3M', '3M 모멘텀', '최근 3개월 수익률'),
  FactorMeta('MOMENTUM_6M', '6M 모멘텀', '최근 6개월 수익률'),
  FactorMeta('MOMENTUM_12M', '12M 모멘텀', '최근 12개월 수익률'),
  FactorMeta('PER', 'PER', '주가수익비율 · TTM 기준 (역수 정렬)'),
  FactorMeta('PBR', 'PBR', '주가순자산비율 (역수 정렬)'),
  FactorMeta('ROE', 'ROE', '자기자본수익률 · TTM 기준'),
  FactorMeta('ROA', 'ROA', '총자산수익률 · TTM 기준'),
  FactorMeta('FOREIGN_NET_20D', '외국인 수급', '20일 누적 외국인 순매수 ÷ 시가총액'),
  FactorMeta('INST_NET_20D', '기관 수급', '20일 누적 기관 순매수 ÷ 시가총액'),
];

class FactorMeta {
  const FactorMeta(this.code, this.label, this.hint);
  final String code;
  final String label;
  final String hint;
}

// 엔진이 지원하는 필터 필드만 (ADV_30D/DEBT_RATIO는 미구현이라 제거,
// TURNOVER_PROXY = 최근일 거래대금 유동성 필터).
const kFilterFields = <String>[
  'TRADING_DAYS_30D',
  'MARKET_CAP',
  'TURNOVER_PROXY',
  'PER',
  'PBR',
];

/// Top-N select-box options (2026-07 표준화 기본값: 10/20/30/50, 기본 20).
const kTopNOptions = <int>[10, 20, 30, 50];

/// One period-preset select-box entry. `years == null` means "직접 지정"
/// (manual date pickers) — [BuilderNotifier.applyPeriodPreset] leaves the
/// current dates untouched for that entry; the rest compute
/// `[today - years, today]`.
class PeriodPresetMeta {
  const PeriodPresetMeta(this.key, this.label, this.years);
  final String key;
  final String label;
  final int? years;
}

const kPeriodPresets = <PeriodPresetMeta>[
  PeriodPresetMeta('1Y', '최근 1년', 1),
  PeriodPresetMeta('2Y', '최근 2년', 2),
  PeriodPresetMeta('3Y', '최근 3년', 3),
  PeriodPresetMeta('5Y', '최근 5년', 5),
  PeriodPresetMeta('CUSTOM', '직접 지정', null),
];

/// One filter-preset select-box entry. `build == null` means "직접 설정"
/// (leave the current filter rows untouched for manual editing).
class FilterPresetMeta {
  const FilterPresetMeta(this.key, this.label, this.build);
  final String key;
  final String label;
  final List<FilterRuleDraft> Function()? build;
}

List<FilterRuleDraft> kDefaultFilterRules() => [
      FilterRuleDraft(field: 'MARKET_CAP', op: BacktestFilterOp.gte, value: 100000000000.0),
      FilterRuleDraft(field: 'TRADING_DAYS_30D', op: BacktestFilterOp.gte, value: 25.0),
    ];

List<FilterRuleDraft> _noFilterRules() => const [];

const kFilterPresets = <FilterPresetMeta>[
  FilterPresetMeta('DEFAULT', '기본 (시가총액 1000억+ · 최근 30일 거래일 25+)', kDefaultFilterRules),
  FilterPresetMeta('NONE', '필터 없음', _noFilterRules),
  FilterPresetMeta('CUSTOM', '직접 설정', null),
];

/// Preset list for the builder's dropdown — `GET /api/backtest/strategies`.
final strategyPresetsProvider = FutureProvider<List<StrategyPresetSummary>>((ref) {
  return ref.read(backtestApiProvider).listStrategies();
});

class BuilderState {
  BuilderState({
    required this.draft,
    this.busy = false,
    this.lastError,
    this.lastRunId,
    this.selectedPresetName,
    this.groupedPreset,
    this.periodPresetKey = 'CUSTOM',
    this.filterPresetKey = 'CUSTOM',
  });

  final StrategyDefinitionDraft draft;
  final bool busy;
  final String? lastError;
  final String? lastRunId;

  /// Name of the currently loaded preset (flat or grouped); null = "직접
  /// 만들기" (scratch).
  final String? selectedPresetName;

  /// Non-null while a *grouped* preset (`groups` non-empty, e.g.
  /// qlab_alpha_v2) is active — the raw `StrategyDefinition` JSON fetched
  /// from the backend, submitted verbatim (plus any top_n/date overrides)
  /// by [BuilderNotifier.run]. The flat factor/filter editors are hidden
  /// while this is set; the builder screen shows a read-only summary
  /// instead ("이 공식 그대로 사용").
  final Map<String, dynamic>? groupedPreset;

  /// Key into [kPeriodPresets] — drives the period select-box highlight.
  final String periodPresetKey;

  /// Key into [kFilterPresets] — drives the filter-preset select-box
  /// highlight (flat/scratch mode only).
  final String filterPresetKey;

  BuilderState copyWith({
    StrategyDefinitionDraft? draft,
    bool? busy,
    String? lastError,
    bool clearError = false,
    String? lastRunId,
    String? selectedPresetName,
    bool clearSelectedPresetName = false,
    Map<String, dynamic>? groupedPreset,
    bool clearGroupedPreset = false,
    String? periodPresetKey,
    String? filterPresetKey,
  }) =>
      BuilderState(
        draft: draft ?? this.draft,
        busy: busy ?? this.busy,
        lastError: clearError ? null : (lastError ?? this.lastError),
        lastRunId: lastRunId ?? this.lastRunId,
        selectedPresetName:
            clearSelectedPresetName ? null : (selectedPresetName ?? this.selectedPresetName),
        groupedPreset: clearGroupedPreset ? null : (groupedPreset ?? this.groupedPreset),
        periodPresetKey: periodPresetKey ?? this.periodPresetKey,
        filterPresetKey: filterPresetKey ?? this.filterPresetKey,
      );

  /// True while a grouped preset ("이 공식 그대로 사용") is active — `run()`
  /// submits [groupedPreset] verbatim instead of `draft.toJson()`.
  bool get isGroupedPresetMode => groupedPreset != null;

  /// Sum of all factor weights — UI uses this to nudge the user.
  double get weightSum => draft.factors.fold(0, (s, f) => s + f.weight);
  bool get isValid =>
      isGroupedPresetMode || (draft.factors.isNotEmpty && draft.topN > 0);
}

class BuilderNotifier extends Notifier<BuilderState> {
  @override
  BuilderState build() {
    // 기본값 표준화(2026-07): topN=20, 기간=최근 3년, 필터=기본(시가총액/거래일).
    final end = DateTime.now();
    final start = DateTime(end.year - 3, end.month, end.day);
    return BuilderState(
      draft: StrategyDefinitionDraft(
        factors: [
          FactorWeightDraft(factor: 'MOMENTUM_1M', weight: 1.0),
        ],
        filters: kDefaultFilterRules(),
        topN: 20,
        startDate: start,
        endDate: end,
      ),
      periodPresetKey: '3Y',
      filterPresetKey: 'DEFAULT',
    );
  }

  void setName(String v) => state = state.copyWith(draft: state.draft.copyWith(name: v));
  void setDescription(String v) =>
      state = state.copyWith(draft: state.draft.copyWith(description: v));
  void setUniverse(BacktestUniverse v) =>
      state = state.copyWith(draft: state.draft.copyWith(universe: v));
  void setRebalance(BacktestRebalanceFreq v) =>
      state = state.copyWith(draft: state.draft.copyWith(rebalanceFreq: v));

  /// Sets top_n — mirrors into [BuilderState.groupedPreset] too so a
  /// grouped-preset override survives into the verbatim POST body.
  void setTopN(int v) {
    final merged =
        state.groupedPreset == null ? null : {...state.groupedPreset!, 'top_n': v};
    state = state.copyWith(draft: state.draft.copyWith(topN: v), groupedPreset: merged);
  }

  void setStartDate(DateTime d) => _updateDates(start: d);
  void setEndDate(DateTime d) => _updateDates(end: d);

  /// Manual date-picker edits fall back to "직접 지정" — they no longer
  /// match any of the [kPeriodPresets] windows once touched by hand.
  void _updateDates({DateTime? start, DateTime? end}) {
    final newStart = start ?? state.draft.startDate;
    final newEnd = end ?? state.draft.endDate;
    final merged = state.groupedPreset == null
        ? null
        : {
            ...state.groupedPreset!,
            'start_date': backtestDateStr(newStart),
            'end_date': backtestDateStr(newEnd),
          };
    state = state.copyWith(
      periodPresetKey: 'CUSTOM',
      draft: state.draft.copyWith(startDate: newStart, endDate: newEnd),
      groupedPreset: merged,
    );
  }

  /// Applies a period-preset select-box choice. "직접 지정" just switches
  /// the highlighted key and leaves the current dates for manual editing;
  /// the rest compute `[today - years, today]`.
  void applyPeriodPreset(String key) {
    final meta = kPeriodPresets.firstWhere(
      (m) => m.key == key,
      orElse: () => kPeriodPresets.last,
    );
    if (meta.years == null) {
      state = state.copyWith(periodPresetKey: key);
      return;
    }
    final end = DateTime.now();
    final start = DateTime(end.year - meta.years!, end.month, end.day);
    final merged = state.groupedPreset == null
        ? null
        : {
            ...state.groupedPreset!,
            'start_date': backtestDateStr(start),
            'end_date': backtestDateStr(end),
          };
    state = state.copyWith(
      periodPresetKey: key,
      draft: state.draft.copyWith(startDate: start, endDate: end),
      groupedPreset: merged,
    );
  }

  // ----- presets -------------------------------------------------------------

  /// Loads a preset by name from `GET /api/backtest/strategies/{name}`.
  /// - Flat preset (`groups` empty/absent, e.g. value_v1) → mapped into
  ///   the editable [StrategyDefinitionDraft] so the user can tweak then run.
  /// - Grouped preset (`groups` non-empty, e.g. qlab_alpha_v2) → switches to
  ///   read-only "이 공식 그대로 사용" mode; [run] submits the raw JSON
  ///   verbatim (plus any top_n/date overrides made afterward).
  Future<void> loadPreset(String name) async {
    if (state.busy) return;
    state = state.copyWith(busy: true, clearError: true);
    try {
      final full = await ref.read(backtestApiProvider).getStrategy(name);
      final groups = full['groups'];
      final isGrouped = groups is List && groups.isNotEmpty;
      if (isGrouped) {
        state = state.copyWith(
          busy: false,
          clearError: true,
          selectedPresetName: name,
          groupedPreset: full,
          periodPresetKey: 'CUSTOM',
        );
      } else {
        state = state.copyWith(
          busy: false,
          clearError: true,
          selectedPresetName: name,
          draft: StrategyDefinitionDraft.fromFlatPreset(full),
          clearGroupedPreset: true,
          periodPresetKey: 'CUSTOM',
          filterPresetKey: 'CUSTOM',
        );
      }
    } catch (e) {
      state = state.copyWith(busy: false, lastError: '$e');
    }
  }

  /// "직접 만들기" — clears any loaded preset and resets to a blank flat
  /// draft with the same sensible defaults as a fresh screen open.
  void clearPreset() {
    state = build();
  }

  // ----- filter presets --------------------------------------------------

  /// Applies a filter-preset select-box choice (flat/scratch mode only —
  /// a grouped preset keeps its own filters verbatim, see
  /// `_GroupedPresetSummaryCard`). "직접 설정" leaves the current filter
  /// rows untouched for manual editing.
  void applyFilterPreset(String key) {
    final meta = kFilterPresets.firstWhere(
      (m) => m.key == key,
      orElse: () => kFilterPresets.last,
    );
    state = state.copyWith(
      filterPresetKey: key,
      draft: meta.build == null ? state.draft : state.draft.copyWith(filters: meta.build!()),
    );
  }

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
  // Manual edits move the filter-preset select-box to "직접 설정" so it
  // doesn't keep showing "기본"/"필터 없음" once the rows no longer match.
  void addFilter() {
    state = state.copyWith(
      filterPresetKey: 'CUSTOM',
      draft: state.draft.copyWith(filters: [
        ...state.draft.filters,
        FilterRuleDraft(field: 'TRADING_DAYS_30D', op: BacktestFilterOp.gte, value: 15.0),
      ]),
    );
  }

  void removeFilter(int idx) {
    final list = [...state.draft.filters]..removeAt(idx);
    state = state.copyWith(filterPresetKey: 'CUSTOM', draft: state.draft.copyWith(filters: list));
  }

  void updateFilter(int idx, FilterRuleDraft v) {
    final list = [...state.draft.filters];
    list[idx] = v;
    state = state.copyWith(filterPresetKey: 'CUSTOM', draft: state.draft.copyWith(filters: list));
  }

  // ----- submit ------------------------------------------------------------
  Future<BacktestRunResult?> run() async {
    if (state.busy) return null;
    state = state.copyWith(busy: true, clearError: true);
    try {
      final api = ref.read(backtestApiProvider);
      // 백테스트랩의 세후(KR) 토글 — 두 실행 경로 모두 ?after_tax로 전달.
      final afterTax = ref.read(afterTaxProvider);
      // Grouped presets ("이 공식 그대로 사용") are submitted verbatim —
      // the flat draft can't represent `groups` scoring at all.
      final result = state.isGroupedPresetMode
          ? await api.runRawStrategy(state.groupedPreset!, afterTax: afterTax)
          : await api.runBacktest(state.draft, afterTax: afterTax);
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
