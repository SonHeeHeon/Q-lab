/// File: app/lib/data/api/backtest_api.dart
///
/// Dio wrapper for `/api/backtest*` (PROJECT_BLUEPRINT.md §8.6).
/// Backend ref: `backend/app/api/backtest.py`.
///
/// Numeric handling: the LIST endpoint returns metrics as Decimal-as-strings
/// while the DETAIL endpoint returns floats. We coerce both transparently.
library;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../parse_utils.dart';
import 'api_client.dart';

class BacktestRunSummary {
  BacktestRunSummary({
    required this.runId,
    required this.strategy,
    required this.startDate,
    required this.endDate,
    required this.finalNav,
    required this.cagr,
    required this.mdd,
    required this.sharpe,
    required this.winRate,
    required this.nTrades,
    required this.topN,
    required this.rebalanceFreq,
    this.gitCommit,
    this.runDir,
  });

  final String runId;
  final String strategy;
  final DateTime startDate;
  final DateTime endDate;
  final double finalNav;
  final double cagr;
  final double mdd;
  final double sharpe;
  final double winRate;
  final int nTrades;
  final int topN;
  final String rebalanceFreq;
  final String? gitCommit;
  final String? runDir;

  factory BacktestRunSummary.fromJson(Map<String, dynamic> j) => BacktestRunSummary(
        runId: j['run_id'] as String,
        strategy: (j['strategy'] as String?) ?? '',
        startDate: DateTime.parse(j['start_date'] as String),
        endDate: DateTime.parse(j['end_date'] as String),
        finalNav: _d(j['final_nav']),
        cagr: _d(j['cagr']),
        mdd: _d(j['mdd']),
        sharpe: _d(j['sharpe']),
        winRate: _d(j['win_rate']),
        nTrades: _i(j['n_trades']),
        topN: _i(j['top_n']),
        rebalanceFreq: (j['rebalance_freq'] as String?) ?? '',
        gitCommit: j['git_commit'] as String?,
        runDir: j['run_dir'] as String?,
      );
}

class BacktestMetrics {
  BacktestMetrics({
    required this.cagr,
    required this.mdd,
    required this.sharpe,
    this.sortino,
    required this.winRate,
    this.avgHoldingDays,
    this.turnover,
    required this.nTrades,
    this.totalTaxPaid,
  });

  final double cagr;
  final double mdd;
  final double sharpe;
  final double? sortino;
  final double winRate;
  final double? avgHoldingDays;
  final double? turnover;
  final int nTrades;

  /// Sum of transaction tax + capital-gains tax across every trade in an
  /// `after_tax=true` run (two-sleeve tax rollout, T8/T9). `null` on runs
  /// that predate this field or weren't run after-tax — never assume 0.0.
  final double? totalTaxPaid;

  factory BacktestMetrics.fromJson(Map<String, dynamic> j) => BacktestMetrics(
        cagr: _d(j['cagr']),
        mdd: _d(j['mdd']),
        sharpe: _d(j['sharpe']),
        sortino: (j['sortino'] as num?)?.toDouble(),
        winRate: _d(j['win_rate']),
        avgHoldingDays: (j['avg_holding_days'] as num?)?.toDouble(),
        turnover: (j['turnover'] as num?)?.toDouble(),
        nTrades: _i(j['n_trades']),
        totalTaxPaid: (j['total_tax_paid'] as num?)?.toDouble(),
      );
}

class BacktestFactor {
  BacktestFactor({required this.factor, required this.weight, this.transform});
  final String factor;
  final double weight;
  final String? transform;
  factory BacktestFactor.fromJson(Map<String, dynamic> j) => BacktestFactor(
        factor: j['factor'] as String,
        weight: _d(j['weight']),
        transform: j['transform'] as String?,
      );
}

class BacktestFilter {
  BacktestFilter({required this.field, required this.op, required this.value});
  final String field;
  final String op;
  final dynamic value;
  factory BacktestFilter.fromJson(Map<String, dynamic> j) => BacktestFilter(
        field: j['field'] as String,
        op: j['op'] as String,
        value: j['value'],
      );
}

class BacktestStrategy {
  BacktestStrategy({
    required this.name,
    this.description,
    required this.universe,
    required this.rebalanceFreq,
    required this.factors,
    required this.filters,
    required this.topN,
    required this.startDate,
    required this.endDate,
  });

  final String name;
  final String? description;
  final String universe;
  final String rebalanceFreq;
  final List<BacktestFactor> factors;
  final List<BacktestFilter> filters;
  final int topN;
  final DateTime startDate;
  final DateTime endDate;

  factory BacktestStrategy.fromJson(Map<String, dynamic> j) => BacktestStrategy(
        name: j['name'] as String,
        description: j['description'] as String?,
        universe: (j['universe'] as String?) ?? '',
        rebalanceFreq: (j['rebalance_freq'] as String?) ?? '',
        factors: ((j['factors'] as List?) ?? const [])
            .map((e) => BacktestFactor.fromJson(asJsonMap(e)))
            .toList(),
        filters: ((j['filters'] as List?) ?? const [])
            .map((e) => BacktestFilter.fromJson(asJsonMap(e)))
            .toList(),
        topN: _i(j['top_n']),
        startDate: DateTime.parse(j['start_date'] as String),
        endDate: DateTime.parse(j['end_date'] as String),
      );
}

class BacktestRunDetail {
  BacktestRunDetail({
    required this.runId,
    required this.metrics,
    required this.strategy,
    this.gitCommit,
    this.rawParams,
    this.trades = const [],
  });

  final String runId;
  final BacktestMetrics metrics;
  final BacktestStrategy strategy;
  final String? gitCommit;
  final Map<String, dynamic>? rawParams;

  /// Trade log for PERSISTED runs (`GET /api/backtest/runs/{id}`). Older
  /// runs predate this field and return an empty list — never absent.
  final List<TradeRecord> trades;

  factory BacktestRunDetail.fromJson(Map<String, dynamic> j) {
    final params = j['params'] is Map ? asJsonMap(j['params']) : <String, dynamic>{};
    final strat = params['strategy'] is Map ? asJsonMap(params['strategy']) : <String, dynamic>{};
    return BacktestRunDetail(
      runId: j['run_id'] as String,
      metrics: BacktestMetrics.fromJson(asJsonMap(j['metrics'])),
      strategy: BacktestStrategy.fromJson(strat),
      gitCommit: params['git_commit'] as String?,
      rawParams: params,
      trades: ((j['trades'] as List?) ?? const [])
          .map((e) => TradeRecord.fromJson(asJsonMap(e)))
          .toList(),
    );
  }
}

// ---------------------------------------------------------------------------
// Equation Builder request DTOs (StrategyDefinition)
// ---------------------------------------------------------------------------

enum BacktestUniverse {
  kospi200('KOSPI200', 'KOSPI 200'),
  kospiTop100('KOSPI_TOP100', 'KOSPI 시총 TOP100'),
  kospiAll('KOSPI_ALL', 'KOSPI 전체'),
  kosdaqAll('KOSDAQ_ALL', 'KOSDAQ 전체'),
  nasdaq100('NASDAQ100', '나스닥 100'),
  etfKr('ETF_KR', '국내 ETF (자산군)'),
  etfUs('ETF_US', '미국 ETF (GTAA)'),
  custom('CUSTOM', '사용자 정의');

  const BacktestUniverse(this.wire, this.label);
  final String wire;
  final String label;

  /// Safe wire-value lookup for presets loaded from the backend — an
  /// unrecognized universe (e.g. backend-only `KOSDAQ150`) falls back to
  /// KOSPI200 rather than throwing.
  static BacktestUniverse fromWire(String? s) => BacktestUniverse.values.firstWhere(
        (e) => e.wire == s,
        orElse: () => BacktestUniverse.kospi200,
      );
}

enum BacktestRebalanceFreq {
  monthly('MONTHLY', '월'),
  quarterly('QUARTERLY', '분기'),
  yearly('YEARLY', '연');

  const BacktestRebalanceFreq(this.wire, this.label);
  final String wire;
  final String label;

  static BacktestRebalanceFreq fromWire(String? s) => BacktestRebalanceFreq.values.firstWhere(
        (e) => e.wire == s,
        orElse: () => BacktestRebalanceFreq.monthly,
      );
}

enum BacktestTransform { raw('RAW'), zscore('ZSCORE'), rank('RANK');
  const BacktestTransform(this.wire);
  final String wire;

  static BacktestTransform fromWire(String? s) => BacktestTransform.values.firstWhere(
        (e) => e.wire == s,
        orElse: () => BacktestTransform.zscore,
      );
}

enum BacktestFilterOp { gt('GT'), gte('GTE'), lt('LT'), lte('LTE'), between('BETWEEN');
  const BacktestFilterOp(this.wire);
  final String wire;

  /// Safe wire-value lookup. The flat filter editor only offers scalar
  /// comparisons (GT/GTE/LT/LTE) — a BETWEEN (range) filter loaded from a
  /// preset falls back to GTE instead of tripping the op dropdown's "value
  /// must match exactly one item" assertion (BETWEEN is never a
  /// selectable item there).
  static BacktestFilterOp fromWire(String? s) {
    for (final op in [gt, gte, lt, lte]) {
      if (op.wire == s) return op;
    }
    return gte;
  }
}

class StrategyDefinitionDraft {
  StrategyDefinitionDraft({
    this.name = 'my_strategy',
    this.description = 'Q-Lab UI builder',
    this.universe = BacktestUniverse.kospi200,
    this.rebalanceFreq = BacktestRebalanceFreq.monthly,
    this.factors = const [],
    this.filters = const [],
    this.topN = 5,
    DateTime? startDate,
    DateTime? endDate,
  })  : startDate = startDate ?? DateTime(2025, 7, 1),
        endDate = endDate ?? DateTime(2026, 5, 27);

  /// Maps a *flat* preset (`is_grouped == false`, e.g. value_v1) fetched
  /// from `GET /api/backtest/strategies/{name}` into an editable draft.
  /// Grouped presets (`groups` non-empty) must NOT go through this path —
  /// their scoring can't round-trip through flat factors; see
  /// `BuilderNotifier.loadPreset`.
  factory StrategyDefinitionDraft.fromFlatPreset(Map<String, dynamic> j) =>
      StrategyDefinitionDraft(
        name: (j['name'] as String?) ?? 'my_strategy',
        description: (j['description'] as String?) ?? '',
        universe: BacktestUniverse.fromWire(j['universe'] as String?),
        rebalanceFreq: BacktestRebalanceFreq.fromWire(j['rebalance_freq'] as String?),
        factors: ((j['factors'] as List?) ?? const [])
            .map((e) => FactorWeightDraft.fromJson(asJsonMap(e)))
            .toList(),
        filters: ((j['filters'] as List?) ?? const [])
            .map((e) => FilterRuleDraft.fromJson(asJsonMap(e)))
            .toList(),
        topN: j['top_n'] == null ? 20 : _i(j['top_n']),
        startDate: j['start_date'] != null ? DateTime.parse(j['start_date'] as String) : null,
        endDate: j['end_date'] != null ? DateTime.parse(j['end_date'] as String) : null,
      );

  final String name;
  final String description;
  final BacktestUniverse universe;
  final BacktestRebalanceFreq rebalanceFreq;
  final List<FactorWeightDraft> factors;
  final List<FilterRuleDraft> filters;
  final int topN;
  final DateTime startDate;
  final DateTime endDate;

  StrategyDefinitionDraft copyWith({
    String? name,
    String? description,
    BacktestUniverse? universe,
    BacktestRebalanceFreq? rebalanceFreq,
    List<FactorWeightDraft>? factors,
    List<FilterRuleDraft>? filters,
    int? topN,
    DateTime? startDate,
    DateTime? endDate,
  }) =>
      StrategyDefinitionDraft(
        name: name ?? this.name,
        description: description ?? this.description,
        universe: universe ?? this.universe,
        rebalanceFreq: rebalanceFreq ?? this.rebalanceFreq,
        factors: factors ?? this.factors,
        filters: filters ?? this.filters,
        topN: topN ?? this.topN,
        startDate: startDate ?? this.startDate,
        endDate: endDate ?? this.endDate,
      );

  Map<String, dynamic> toJson() => {
        'name': name,
        'description': description,
        'universe': universe.wire,
        'rebalance_freq': rebalanceFreq.wire,
        'factors': [for (final f in factors) f.toJson()],
        'filters': [for (final f in filters) f.toJson()],
        'top_n': topN,
        'start_date': backtestDateStr(startDate),
        'end_date': backtestDateStr(endDate),
      };
}

/// Formats a date as `yyyy-MM-dd` — the wire format `StrategyDefinition`
/// expects for `start_date`/`end_date`. Shared by [StrategyDefinitionDraft.
/// toJson] and the raw-preset date-override path (a grouped preset's dates
/// live as plain strings in the fetched JSON, not [DateTime]).
String backtestDateStr(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-'
    '${d.month.toString().padLeft(2, '0')}-'
    '${d.day.toString().padLeft(2, '0')}';

class FactorWeightDraft {
  FactorWeightDraft({required this.factor, required this.weight, this.transform = BacktestTransform.zscore});
  final String factor;
  final double weight;
  final BacktestTransform transform;

  factory FactorWeightDraft.fromJson(Map<String, dynamic> j) => FactorWeightDraft(
        factor: j['factor'] as String,
        weight: _d(j['weight']),
        transform: BacktestTransform.fromWire(j['transform'] as String?),
      );

  Map<String, dynamic> toJson() => {
        'factor': factor,
        'weight': weight,
        'transform': transform.wire,
      };
}

class FilterRuleDraft {
  FilterRuleDraft({required this.field, required this.op, required this.value});
  final String field;
  final BacktestFilterOp op;
  final dynamic value; // num or List<num>

  /// Field names are uppercased to match [kFilterFields] — the backend
  /// engine itself uppercases `rule.field` before comparing
  /// (`research/backtest/engine.py`), so presets authored with lowercase
  /// YAML keys (`market_cap`) still resolve to a valid dropdown item
  /// instead of tripping Flutter's "value must match exactly one item"
  /// assertion.
  factory FilterRuleDraft.fromJson(Map<String, dynamic> j) => FilterRuleDraft(
        field: (j['field'] as String).toUpperCase(),
        op: BacktestFilterOp.fromWire(j['op'] as String?),
        value: j['value'],
      );

  Map<String, dynamic> toJson() => {
        'field': field,
        'op': op.wire,
        'value': value,
      };
}

/// Lightweight preset metadata from `GET /api/backtest/strategies` — enough
/// to render the builder's preset dropdown without fetching every full
/// definition upfront.
class StrategyPresetSummary {
  StrategyPresetSummary({
    required this.name,
    required this.description,
    this.universe,
    this.rebalanceFreq,
    this.topN,
    required this.isPrivate,
    required this.isGrouped,
  });

  final String name;
  final String description;
  final String? universe;
  final String? rebalanceFreq;
  final int? topN;

  /// Loaded from `research/strategies/private/` (gitignored, e.g.
  /// qlab_alpha_v2) rather than the public `research/strategies/` dir.
  final bool isPrivate;

  /// True when the preset scores via `groups` (composite scorer) instead
  /// of flat `factors` — the builder must use it read-only/verbatim
  /// rather than loading it into the editable factor list.
  final bool isGrouped;

  factory StrategyPresetSummary.fromJson(Map<String, dynamic> j) => StrategyPresetSummary(
        name: j['name'] as String,
        description: (j['description'] as String?) ?? '',
        universe: j['universe'] as String?,
        rebalanceFreq: j['rebalance_freq'] as String?,
        topN: j['top_n'] == null ? null : _i(j['top_n']),
        isPrivate: (j['is_private'] as bool?) ?? false,
        isGrouped: (j['is_grouped'] as bool?) ?? false,
      );
}

// ---------------------------------------------------------------------------
// Run result (POST /api/backtest/run response)
// ---------------------------------------------------------------------------

class EquityPoint {
  EquityPoint({required this.date, required this.nav});
  final DateTime date;
  final double nav;
  factory EquityPoint.fromJson(Map<String, dynamic> j) =>
      EquityPoint(date: DateTime.parse(j['date'] as String), nav: _d(j['nav']));
}

class TradeRecord {
  TradeRecord({
    required this.date,
    required this.code,
    required this.side,
    required this.qty,
    required this.price,
    required this.cashFlow,
    this.reason,
    this.gainsTax,
  });
  final DateTime date;
  final String code;
  final String side;
  final int qty;
  final double price;
  final double cashFlow;

  /// Structured reason the strategy engine bought/sold this, e.g.
  /// `{"rule": "STOP_LOSS", "return": -0.12}`. Nullable — older persisted
  /// runs predate this field. Drives `ReasonChip`.
  final Map<String, dynamic>? reason;

  /// Capital-gains tax charged against this SELL in an `after_tax=true`
  /// run (0.0 on tax-exempt instruments, `null` on runs without tax
  /// modeling / older persisted runs).
  final double? gainsTax;

  factory TradeRecord.fromJson(Map<String, dynamic> j) => TradeRecord(
        date: DateTime.parse(j['date'] as String),
        code: j['code'] as String,
        side: j['side'] as String,
        qty: _i(j['qty']),
        price: _d(j['price']),
        cashFlow: _d(j['cash_flow']),
        reason: j['reason'] is Map ? asJsonMap(j['reason']) : null,
        gainsTax: (j['gains_tax'] as num?)?.toDouble(),
      );
}

class BacktestRunResult {
  BacktestRunResult({
    required this.runId,
    required this.runDir,
    required this.strategyName,
    required this.startDate,
    required this.endDate,
    required this.initialNav,
    required this.finalNav,
    required this.metrics,
    required this.equityCurve,
    required this.trades,
    required this.warnings,
    this.afterTax = false,
  });

  final String runId;
  final String runDir;
  final String strategyName;
  final DateTime startDate;
  final DateTime endDate;
  final double initialNav;
  final double finalNav;
  final BacktestMetrics metrics;
  final List<EquityPoint> equityCurve;
  final List<TradeRecord> trades;
  final List<String> warnings;

  /// Whether the backend actually applied tax modeling (`POST .../run
  /// ?after_tax=true`). May be `false` even when the caller *requested*
  /// after-tax if the strategy's universe doesn't support it yet (e.g. US)
  /// — that fallback is surfaced as a message in [warnings] instead.
  final bool afterTax;

  factory BacktestRunResult.fromJson(Map<String, dynamic> j) {
    final result = asJsonMap(j['result']);
    // Warnings can come from two sources: the engine itself (nested inside
    // `result`, e.g. missing price rows) and the API layer's after-tax
    // fallback notice (top-level `data.warnings`, e.g. unsupported
    // universe). Both matter to the user, so merge them into one list for
    // the run detail screen's Warnings card.
    final warnings = <String>[
      ...((result['warnings'] as List?) ?? const []).map((e) => e.toString()),
      ...((j['warnings'] as List?) ?? const []).map((e) => e.toString()),
    ];
    return BacktestRunResult(
      runId: j['run_id'] as String,
      runDir: (j['run_dir'] as String?) ?? '',
      strategyName: (result['strategy_name'] as String?) ?? '',
      startDate: DateTime.parse(result['start_date'] as String),
      endDate: DateTime.parse(result['end_date'] as String),
      initialNav: _d(result['initial_nav']),
      finalNav: _d(result['final_nav']),
      metrics: BacktestMetrics.fromJson(asJsonMap(result['metrics'])),
      equityCurve: ((result['equity_curve'] as List?) ?? const [])
          .map((e) => EquityPoint.fromJson(asJsonMap(e)))
          .toList(),
      trades: ((result['trades'] as List?) ?? const [])
          .map((e) => TradeRecord.fromJson(asJsonMap(e)))
          .toList(),
      warnings: warnings,
      afterTax: (j['after_tax'] as bool?) ?? false,
    );
  }
}

// ---------------------------------------------------------------------------
// Multi-sleeve portfolio backtest (POST /api/backtest/run-portfolio, T-P3)
//
// Blends N strategy presets ("sleeves") at fixed weights into one combined
// backtest, optionally searching for better weights (`optimize`) and
// validating that search out-of-sample (`oos`). Reuses [BacktestMetrics]
// throughout — the combined curve and each sleeve report the exact same
// metric shape as a single-strategy run.
// ---------------------------------------------------------------------------

/// One sleeve in a portfolio request — a strategy preset name (any
/// `GET /api/backtest/strategies` entry, flat or grouped) plus its target
/// blend weight. Weights are normalized client-side before submit (see
/// [normalizeSleeveWeights]) so they needn't sum to exactly 1.0 in the UI.
class PortfolioSleeveRequest {
  PortfolioSleeveRequest({required this.strategyName, required this.weight});
  final String strategyName;
  final double weight;
  Map<String, dynamic> toJson() => {'strategy_name': strategyName, 'weight': weight};
}

/// One sleeve's contribution inside a `POST /api/backtest/run-portfolio`
/// response — the weight actually applied plus that sleeve's own
/// standalone metrics (as if it alone had been backtested).
class PortfolioSleeve {
  PortfolioSleeve({required this.strategyName, required this.weight, required this.metrics});
  final String strategyName;
  final double weight;
  final BacktestMetrics metrics;

  factory PortfolioSleeve.fromJson(Map<String, dynamic> j) => PortfolioSleeve(
        strategyName: (j['strategy_name'] as String?) ?? '',
        weight: _d(j['weight']),
        metrics: BacktestMetrics.fromJson(asJsonMap(j['metrics'])),
      );
}

/// In-sample weight-search result (`optimize=true`) — the blend weights
/// that best maximize [objective] purely within the backtest window
/// itself. This is the "탐색용" half of [PortfolioOptimal]; on its own it
/// is prone to overfitting on exactly the data it was searched against.
class PortfolioOptimalInsample {
  PortfolioOptimalInsample({
    required this.weights,
    required this.objective,
    required this.value,
    required this.trials,
  });
  final List<double> weights;
  final String objective;
  final double value;
  final int trials;

  factory PortfolioOptimalInsample.fromJson(Map<String, dynamic> j) => PortfolioOptimalInsample(
        weights: ((j['weights'] as List?) ?? const []).map(_d).toList(),
        objective: (j['objective'] as String?) ?? '',
        value: _d(j['value']),
        trials: _i(j['trials']),
      );
}

/// Out-of-sample (walk-forward fold) validation of the optimizer
/// (`optimize=true, oos=true`) — the honest number to trust over
/// [PortfolioOptimalInsample.value], since [oosMetricMean] is averaged
/// across folds the search never touched directly.
class PortfolioOptimalOos {
  PortfolioOptimalOos({required this.weights, required this.oosMetricMean, required this.folds});
  final List<double> weights;
  final double oosMetricMean;
  final int folds;

  factory PortfolioOptimalOos.fromJson(Map<String, dynamic> j) => PortfolioOptimalOos(
        weights: ((j['weights'] as List?) ?? const []).map(_d).toList(),
        oosMetricMean: _d(j['oos_metric_mean']),
        folds: _i(j['folds']),
      );
}

/// `optimize=true`'s combined weight-search result. The backend returns a
/// bare `{}` when `optimize=false` — [PortfolioOptimal.empty] models that
/// case so callers can branch on [isEmpty] instead of null-checking two
/// fields separately. [oos] is further gated behind the request's own
/// `oos=true` flag even when [insample] succeeded.
class PortfolioOptimal {
  const PortfolioOptimal({this.insample, this.oos});
  final PortfolioOptimalInsample? insample;
  final PortfolioOptimalOos? oos;

  static const empty = PortfolioOptimal();

  bool get isEmpty => insample == null && oos == null;

  factory PortfolioOptimal.fromJson(Map<String, dynamic> j) => PortfolioOptimal(
        insample:
            j['insample'] is Map ? PortfolioOptimalInsample.fromJson(asJsonMap(j['insample'])) : null,
        oos: j['oos'] is Map ? PortfolioOptimalOos.fromJson(asJsonMap(j['oos'])) : null,
      );
}

/// `POST /api/backtest/run-portfolio` response.
class PortfolioRunResult {
  PortfolioRunResult({
    required this.portfolioId,
    required this.rebalance,
    required this.afterTax,
    required this.weights,
    required this.combinedMetrics,
    required this.sleeves,
    required this.optimal,
  });

  final String portfolioId;

  /// Wire value, e.g. `QUARTERLY` — see [BacktestRebalanceFreq.fromWire].
  final String rebalance;
  final bool afterTax;

  /// Resolved blend weights, parallel to [sleeves] by index (duplicates
  /// each sleeve's own `.weight`, kept at top level for symmetry with the
  /// list/detail endpoints where there's no nested sleeve object).
  final List<double> weights;
  final BacktestMetrics combinedMetrics;
  final List<PortfolioSleeve> sleeves;

  /// `PortfolioOptimal.empty` when the request didn't set `optimize=true`.
  final PortfolioOptimal optimal;

  factory PortfolioRunResult.fromJson(Map<String, dynamic> j) => PortfolioRunResult(
        portfolioId: (j['portfolio_id'] as String?) ?? '',
        rebalance: (j['rebalance'] as String?) ?? '',
        afterTax: (j['after_tax'] as bool?) ?? false,
        weights: ((j['weights'] as List?) ?? const []).map(_d).toList(),
        combinedMetrics: BacktestMetrics.fromJson(asJsonMap(j['combined_metrics'])),
        sleeves: ((j['sleeves'] as List?) ?? const [])
            .map((e) => PortfolioSleeve.fromJson(asJsonMap(e)))
            .toList(),
        optimal:
            j['optimal'] is Map ? PortfolioOptimal.fromJson(asJsonMap(j['optimal'])) : PortfolioOptimal.empty,
      );
}

/// `GET /api/backtest/portfolios` list-row summary. Persisted alongside
/// single-strategy runs in a CSV leaderboard, so numeric fields may arrive
/// as strings — same Decimal-as-string caveat as [BacktestRunSummary].
class PortfolioSummary {
  PortfolioSummary({
    required this.portfolioId,
    required this.sleeves,
    required this.weights,
    required this.cagr,
    required this.mdd,
    required this.sharpe,
    this.runDir,
  });

  final String portfolioId;
  final List<String> sleeves;
  final List<double> weights;
  final double cagr;
  final double mdd;
  final double sharpe;
  final String? runDir;

  factory PortfolioSummary.fromJson(Map<String, dynamic> j) => PortfolioSummary(
        portfolioId: (j['portfolio_id'] as String?) ?? '',
        sleeves: _stringList(j['sleeves']),
        weights: ((j['weights'] as List?) ?? const []).map(_d).toList(),
        cagr: _d(j['cagr']),
        mdd: _d(j['mdd']),
        sharpe: _d(j['sharpe']),
        runDir: j['run_dir'] as String?,
      );
}

/// `GET /api/backtest/portfolios/{id}` — combined metrics + blended equity
/// curve. Unlike [PortfolioRunResult] (the POST response), this endpoint
/// has no nested per-sleeve metrics object — [sleeves] is just the
/// strategy-name roster, weight-paired via index into [weights].
class PortfolioDetail {
  PortfolioDetail({
    required this.portfolioId,
    required this.combinedMetrics,
    required this.weights,
    required this.sleeves,
    required this.blendedCurve,
  });

  final String portfolioId;
  final BacktestMetrics combinedMetrics;
  final List<double> weights;
  final List<String> sleeves;
  final List<EquityPoint> blendedCurve;

  factory PortfolioDetail.fromJson(Map<String, dynamic> j) => PortfolioDetail(
        portfolioId: (j['portfolio_id'] as String?) ?? '',
        combinedMetrics: BacktestMetrics.fromJson(asJsonMap(j['combined_metrics'])),
        weights: ((j['weights'] as List?) ?? const []).map(_d).toList(),
        sleeves: _stringList(j['sleeves']),
        blendedCurve: ((j['blended_curve'] as List?) ?? const [])
            .map((e) => EquityPoint.fromJson(asJsonMap(e)))
            .toList(),
      );
}

/// Rescales [weights] so they sum to 1.0, preserving relative proportions.
/// No-op (returns [weights] unchanged) on an empty list or a non-positive
/// sum — callers should guard "정규화" affordances on `sum > 0` the same
/// way `BuilderNotifier.normalizeWeights` guards factor weights.
List<double> normalizeSleeveWeights(List<double> weights) {
  final sum = weights.fold(0.0, (s, w) => s + w);
  if (weights.isEmpty || sum <= 0) return weights;
  return [for (final w in weights) w / sum];
}

/// Defensive string-list coercion for [PortfolioSummary]/[PortfolioDetail]'s
/// `sleeves` field — tolerates either a plain list of strategy-name strings
/// or (if a future backend revision nests sleeve objects here too) a list
/// of maps carrying `strategy_name`/`name`.
List<String> _stringList(Object? v) {
  if (v is! List) return const [];
  return v.map((e) {
    if (e is String) return e;
    if (e is Map) return (e['strategy_name'] ?? e['name'] ?? '').toString();
    return e.toString();
  }).toList();
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

class BacktestApi {
  BacktestApi(this._ref);
  final Ref _ref;

  Future<List<BacktestRunSummary>> listRuns() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/backtest/runs');
    final list = (res.data as List?) ?? const [];
    return list.map((e) => BacktestRunSummary.fromJson(asJsonMap(e))).toList();
  }

  Future<BacktestRunDetail> getRun(String runId) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/backtest/runs/$runId');
    return BacktestRunDetail.fromJson(asJsonMap(res.data));
  }

  /// Executes the strategy and returns the full result (incl. equity_curve).
  /// Backtests can run for many seconds, so the per-call timeout is widened.
  ///
  /// [afterTax] threads through as the `?after_tax=true` query param (the
  /// request body stays the bare `StrategyDefinition` — the backend can't
  /// take it as a body field). See `backend/app/api/backtest.py`.
  Future<BacktestRunResult> runBacktest(
    StrategyDefinitionDraft draft, {
    bool afterTax = false,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/backtest/run',
      data: draft.toJson(),
      queryParameters: afterTax ? {'after_tax': true} : null,
      options: Options(
        receiveTimeout: const Duration(seconds: 300),
        sendTimeout: const Duration(seconds: 300),
      ),
    );
    return BacktestRunResult.fromJson(asJsonMap(res.data));
  }

  /// Lists usable strategy presets (private dir shadows public) for the
  /// builder's preset dropdown.
  Future<List<StrategyPresetSummary>> listStrategies() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/backtest/strategies');
    final list = (res.data as List?) ?? const [];
    return list.map((e) => StrategyPresetSummary.fromJson(asJsonMap(e))).toList();
  }

  /// Fetches the full `StrategyDefinition` JSON for one preset — includes
  /// `groups`/`min_groups`/`winsor_pct`/etc. that the flat
  /// [StrategyDefinitionDraft] cannot represent. Returned raw (not parsed
  /// into a Dart model) because grouped presets are submitted verbatim via
  /// [runRawStrategy] rather than round-tripped through the draft.
  Future<Map<String, dynamic>> getStrategy(String name) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/backtest/strategies/$name');
    return asJsonMap(res.data);
  }

  /// Runs a raw `StrategyDefinition` JSON verbatim (with optional
  /// top_n/date overrides already merged in by the caller) — the "이 공식
  /// 그대로 사용" path for grouped presets, which can't round-trip through
  /// [StrategyDefinitionDraft.toJson].
  Future<BacktestRunResult> runRawStrategy(
    Map<String, dynamic> strategy, {
    bool afterTax = false,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/backtest/run',
      data: strategy,
      queryParameters: afterTax ? {'after_tax': true} : null,
      options: Options(
        receiveTimeout: const Duration(seconds: 300),
        sendTimeout: const Duration(seconds: 300),
      ),
    );
    return BacktestRunResult.fromJson(asJsonMap(res.data));
  }

  // ----- multi-sleeve portfolio (T-P3) --------------------------------------

  /// Runs a blended multi-sleeve portfolio backtest. Each sleeve backtests
  /// independently before blending, and `optimize`/`oos` add a weight
  /// search (+ walk-forward folds) on top of that — noticeably slower than
  /// [runBacktest], so the timeout is widened the same way.
  Future<PortfolioRunResult> runPortfolio({
    required List<PortfolioSleeveRequest> sleeves,
    required BacktestRebalanceFreq rebalance,
    bool optimize = false,
    bool oos = false,
    bool afterTax = false,
  }) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>(
      '/api/backtest/run-portfolio',
      data: {
        'sleeves': [for (final s in sleeves) s.toJson()],
        'rebalance': rebalance.wire,
        'optimize': optimize,
        'oos': oos,
      },
      queryParameters: afterTax ? {'after_tax': true} : null,
      options: Options(
        receiveTimeout: const Duration(seconds: 300),
        sendTimeout: const Duration(seconds: 300),
      ),
    );
    return PortfolioRunResult.fromJson(asJsonMap(res.data));
  }

  /// Saved-portfolio leaderboard (mirrors [listRuns] for single strategies).
  Future<List<PortfolioSummary>> getPortfolios() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/backtest/portfolios');
    final list = (res.data as List?) ?? const [];
    return list.map((e) => PortfolioSummary.fromJson(asJsonMap(e))).toList();
  }

  /// One saved portfolio's combined metrics + blended equity curve (mirrors
  /// [getRun] for single strategies).
  Future<PortfolioDetail> getPortfolio(String portfolioId) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/backtest/portfolios/$portfolioId');
    return PortfolioDetail.fromJson(asJsonMap(res.data));
  }
}

final backtestApiProvider = Provider<BacktestApi>((ref) => BacktestApi(ref));

/// Saved-portfolio leaderboard — parallels `backtestRunsProvider`
/// (`backtest_lab_controller.dart`) but for multi-sleeve portfolios.
final portfolioListProvider = FutureProvider<List<PortfolioSummary>>((ref) {
  return ref.read(backtestApiProvider).getPortfolios();
});

/// One saved portfolio's detail (combined metrics + blended curve), keyed
/// by `portfolio_id`.
final portfolioDetailProvider =
    FutureProvider.family<PortfolioDetail, String>((ref, portfolioId) {
  return ref.read(backtestApiProvider).getPortfolio(portfolioId);
});

double _d(Object? v) => safeDouble(v, hint: 'backtest');
int _i(Object? v) => safeInt(v, hint: 'backtest');
