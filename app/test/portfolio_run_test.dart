/// Test seed: multi-sleeve portfolio backtest (T-P3).
///   - `PortfolioRunResult.fromJson` parses the documented
///     `POST /api/backtest/run-portfolio` response shape, including both
///     `optimal.insample`/`optimal.oos` present and the `optimal: {}`
///     (optimize=false) case.
///   - `PortfolioSummary.fromJson` / `PortfolioDetail.fromJson` parse the
///     `GET /api/backtest/portfolios` (list, string-typed metrics from CSV)
///     and `GET /api/backtest/portfolios/{id}` (detail, blended_curve) shapes.
///   - `normalizeSleeveWeights` — pure weight-normalization helper shared by
///     the "정규화" button and the auto-normalize-on-run path.
///   - `PortfolioRunNotifier` — sleeve add/remove floor/ceiling, weight
///     edits, and the `isValid`/`weightSumValid` state contracts the run
///     screen's FAB and sum indicator rely on (pure state, no network).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/backtest_api.dart';
import 'package:qlab/presentation/quant/backtest_lab/portfolio_run_controller.dart';

Map<String, dynamic> _metricsJson({double cagr = 0.15, double mdd = -0.18, double sharpe = 1.2}) => {
      'cagr': cagr,
      'mdd': mdd,
      'sharpe': sharpe,
      'sortino': 1.4,
      'win_rate': 0.58,
      'avg_holding_days': 21.0,
      'turnover': 0.4,
      'n_trades': 42,
    };

void main() {
  group('PortfolioRunResult.fromJson', () {
    Map<String, dynamic> baseJson({Map<String, dynamic>? optimal}) => {
          'portfolio_id': 'pf_20260727_001',
          'rebalance': 'QUARTERLY',
          'after_tax': true,
          'weights': [0.6, 0.4],
          'combined_metrics': _metricsJson(cagr: 0.22, mdd: -0.15, sharpe: 1.5),
          'sleeves': [
            {
              'strategy_name': 'value_v1',
              'weight': 0.6,
              'metrics': _metricsJson(cagr: 0.18, mdd: -0.2, sharpe: 1.1),
            },
            {
              'strategy_name': 'momentum_v1',
              'weight': 0.4,
              'metrics': _metricsJson(cagr: 0.28, mdd: -0.25, sharpe: 1.3),
            },
          ],
          if (optimal != null) 'optimal': optimal,
        };

    test('parses the full documented shape with optimal.insample + oos', () {
      final j = baseJson(optimal: {
        'insample': {
          'weights': [0.7, 0.3],
          'objective': 'sharpe',
          'value': 1.62,
          'trials': 200,
        },
        'oos': {
          'weights': [0.65, 0.35],
          'oos_metric_mean': 1.31,
          'folds': 5,
        },
      });
      final r = PortfolioRunResult.fromJson(j);

      expect(r.portfolioId, 'pf_20260727_001');
      expect(r.rebalance, 'QUARTERLY');
      expect(r.afterTax, isTrue);
      expect(r.weights, [0.6, 0.4]);
      expect(r.combinedMetrics.cagr, 0.22);
      expect(r.combinedMetrics.sharpe, 1.5);

      expect(r.sleeves, hasLength(2));
      expect(r.sleeves[0].strategyName, 'value_v1');
      expect(r.sleeves[0].weight, 0.6);
      expect(r.sleeves[0].metrics.cagr, 0.18);
      expect(r.sleeves[1].strategyName, 'momentum_v1');
      expect(r.sleeves[1].metrics.sharpe, 1.3);

      expect(r.optimal.isEmpty, isFalse);
      expect(r.optimal.insample, isNotNull);
      expect(r.optimal.insample!.weights, [0.7, 0.3]);
      expect(r.optimal.insample!.objective, 'sharpe');
      expect(r.optimal.insample!.value, 1.62);
      expect(r.optimal.insample!.trials, 200);
      expect(r.optimal.oos, isNotNull);
      expect(r.optimal.oos!.weights, [0.65, 0.35]);
      expect(r.optimal.oos!.oosMetricMean, 1.31);
      expect(r.optimal.oos!.folds, 5);
    });

    test('parses optimal.insample only (optimize=true, oos=false)', () {
      final j = baseJson(optimal: {
        'insample': {
          'weights': [0.5, 0.5],
          'objective': 'cagr',
          'value': 0.24,
          'trials': 100,
        },
      });
      final r = PortfolioRunResult.fromJson(j);
      expect(r.optimal.isEmpty, isFalse);
      expect(r.optimal.insample, isNotNull);
      expect(r.optimal.oos, isNull);
    });

    test('optimal: {} (optimize=false) parses as PortfolioOptimal.empty', () {
      final j = baseJson(optimal: {});
      final r = PortfolioRunResult.fromJson(j);
      expect(r.optimal.isEmpty, isTrue);
      expect(r.optimal.insample, isNull);
      expect(r.optimal.oos, isNull);
    });

    test('missing optimal key entirely also falls back to empty (defensive)', () {
      final j = baseJson();
      final r = PortfolioRunResult.fromJson(j);
      expect(r.optimal.isEmpty, isTrue);
    });
  });

  group('PortfolioSummary.fromJson (GET /api/backtest/portfolios)', () {
    test('parses numeric fields as native doubles', () {
      final p = PortfolioSummary.fromJson({
        'portfolio_id': 'pf_1',
        'sleeves': ['value_v1', 'momentum_v1'],
        'weights': [0.6, 0.4],
        'cagr': 0.22,
        'mdd': -0.15,
        'sharpe': 1.5,
        'run_dir': 'research/runs/pf_1',
      });
      expect(p.portfolioId, 'pf_1');
      expect(p.sleeves, ['value_v1', 'momentum_v1']);
      expect(p.weights, [0.6, 0.4]);
      expect(p.cagr, 0.22);
      expect(p.mdd, -0.15);
      expect(p.sharpe, 1.5);
      expect(p.runDir, 'research/runs/pf_1');
    });

    test('tolerates Decimal-as-string numeric fields (CSV round trip)', () {
      final p = PortfolioSummary.fromJson({
        'portfolio_id': 'pf_2',
        'sleeves': ['value_v1', 'momentum_v1'],
        'weights': [0.5, 0.5],
        'cagr': '0.19',
        'mdd': '-0.22',
        'sharpe': '1.1',
      });
      expect(p.cagr, 0.19);
      expect(p.mdd, -0.22);
      expect(p.sharpe, 1.1);
      expect(p.runDir, isNull);
    });
  });

  group('PortfolioDetail.fromJson (GET /api/backtest/portfolios/{id})', () {
    test('parses combined metrics, weights, sleeves, and the blended curve', () {
      final d = PortfolioDetail.fromJson({
        'portfolio_id': 'pf_1',
        'combined_metrics': _metricsJson(cagr: 0.2, mdd: -0.14, sharpe: 1.4),
        'weights': [0.6, 0.4],
        'sleeves': ['value_v1', 'momentum_v1'],
        'blended_curve': [
          {'date': '2026-01-01', 'nav': 100000000.0},
          {'date': '2026-01-02', 'nav': 100500000.0},
        ],
      });
      expect(d.portfolioId, 'pf_1');
      expect(d.combinedMetrics.cagr, 0.2);
      expect(d.weights, [0.6, 0.4]);
      expect(d.sleeves, ['value_v1', 'momentum_v1']);
      expect(d.blendedCurve, hasLength(2));
      expect(d.blendedCurve[1].nav, 100500000.0);
    });

    test('missing blended_curve defaults to an empty list, not a throw', () {
      final d = PortfolioDetail.fromJson({
        'portfolio_id': 'pf_2',
        'combined_metrics': _metricsJson(),
        'weights': [1.0],
        'sleeves': ['value_v1'],
      });
      expect(d.blendedCurve, isEmpty);
    });
  });

  group('normalizeSleeveWeights', () {
    test('rescales weights that already sum to something other than 1.0', () {
      final result = normalizeSleeveWeights([2.0, 2.0]);
      expect(result[0], closeTo(0.5, 1e-9));
      expect(result[1], closeTo(0.5, 1e-9));
    });

    test('preserves relative proportions across uneven weights', () {
      final result = normalizeSleeveWeights([1.0, 3.0]);
      expect(result[0], closeTo(0.25, 1e-9));
      expect(result[1], closeTo(0.75, 1e-9));
    });

    test('is a no-op on an empty list', () {
      expect(normalizeSleeveWeights([]), isEmpty);
    });

    test('is a no-op when the sum is zero or negative', () {
      expect(normalizeSleeveWeights([0.0, 0.0]), [0.0, 0.0]);
      expect(normalizeSleeveWeights([-1.0, -1.0]), [-1.0, -1.0]);
    });

    test('already-normalized weights round-trip unchanged', () {
      final result = normalizeSleeveWeights([0.5, 0.5]);
      expect(result[0], closeTo(0.5, 1e-9));
      expect(result[1], closeTo(0.5, 1e-9));
    });
  });

  group('PortfolioRunNotifier', () {
    test('starts with 2 sleeves at 50/50, no result, not busy', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(portfolioRunProvider.notifier);

      expect(notifier.state.sleeves, hasLength(2));
      expect(notifier.state.sleeves[0].weight, 0.5);
      expect(notifier.state.sleeves[1].weight, 0.5);
      expect(notifier.state.rebalance, BacktestRebalanceFreq.quarterly);
      expect(notifier.state.result, isNull);
      expect(notifier.state.busy, isFalse);
      // Names are unset, so the form isn't runnable yet.
      expect(notifier.state.isValid, isFalse);
    });

    test('addSleeve appends a 0%-weight row up to kMaxSleeves, then no-ops', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(portfolioRunProvider.notifier);

      for (var i = 2; i < kMaxSleeves; i++) {
        notifier.addSleeve();
      }
      expect(notifier.state.sleeves, hasLength(kMaxSleeves));
      notifier.addSleeve(); // at ceiling — no-op
      expect(notifier.state.sleeves, hasLength(kMaxSleeves));
    });

    test('removeSleeve stops at kMinSleeves (floor)', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(portfolioRunProvider.notifier);

      expect(notifier.state.sleeves, hasLength(kMinSleeves));
      notifier.removeSleeve(0); // already at floor — no-op
      expect(notifier.state.sleeves, hasLength(kMinSleeves));
    });

    test('setStrategyName + weightSum/weightSumValid/isValid track edits', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(portfolioRunProvider.notifier);

      notifier.setStrategyName(0, 'value_v1');
      notifier.setStrategyName(1, 'momentum_v1');
      expect(notifier.state.isValid, isTrue); // 50/50 already sums to 1.0
      expect(notifier.state.weightSumValid, isTrue);

      notifier.setWeight(0, 0.8);
      notifier.setWeight(1, 0.8);
      expect(notifier.state.weightSum, closeTo(1.6, 1e-9));
      expect(notifier.state.weightSumValid, isFalse);
      // Still valid (a positive sum) — run() auto-normalizes rather than
      // blocking on an imperfect sum.
      expect(notifier.state.isValid, isTrue);
    });

    test('normalizeWeights rescales sleeve weights to sum to 1.0', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(portfolioRunProvider.notifier);

      notifier.setWeight(0, 3.0);
      notifier.setWeight(1, 1.0);
      notifier.normalizeWeights();
      expect(notifier.state.sleeves[0].weight, closeTo(0.75, 1e-9));
      expect(notifier.state.sleeves[1].weight, closeTo(0.25, 1e-9));
      expect(notifier.state.weightSumValid, isTrue);
    });

    test('setOptimize(false) also clears oos', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(portfolioRunProvider.notifier);

      notifier.setOptimize(true);
      notifier.setOos(true);
      expect(notifier.state.oos, isTrue);

      notifier.setOptimize(false);
      expect(notifier.state.optimize, isFalse);
      expect(notifier.state.oos, isFalse);
    });
  });
}
