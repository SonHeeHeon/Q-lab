/// Test seed: the 가치 방정식 빌더 preset picker.
///   - `StrategyPresetSummary.fromJson` parses `GET /api/backtest/strategies`
///     list items (nullable universe/rebalance_freq/top_n survive missing
///     YAML keys without throwing).
///   - `StrategyDefinitionDraft.fromFlatPreset` maps a *flat* preset (e.g.
///     value_v1) into the editable draft — including the lowercase→UPPERCASE
///     filter-field normalization the flat filter dropdown requires.
///   - `BacktestFilterOp.fromWire` never returns BETWEEN (the flat op
///     dropdown doesn't offer it — returning it would crash the picker).
///   - `kTopNOptions` / `kPeriodPresets` / `kFilterPresets` — the new
///     default-option select-box constants.
///   - `BuilderNotifier` preset-preset/period-preset/filter-preset apply +
///     auto-flip-to-CUSTOM transitions (pure state, no network).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/backtest_api.dart';
import 'package:qlab/presentation/quant/builder/builder_controller.dart';

void main() {
  group('StrategyPresetSummary.fromJson', () {
    test('parses a grouped private preset (qlab_alpha_v2-shaped)', () {
      final p = StrategyPresetSummary.fromJson({
        'name': 'qlab_alpha_v2',
        'description': '4계층 방정식 v2',
        'universe': 'KOSPI200',
        'rebalance_freq': 'QUARTERLY',
        'top_n': 20,
        'is_private': true,
        'is_grouped': true,
      });
      expect(p.name, 'qlab_alpha_v2');
      expect(p.isPrivate, isTrue);
      expect(p.isGrouped, isTrue);
      expect(p.topN, 20);
    });

    test('parses a flat public preset (value_v1-shaped)', () {
      final p = StrategyPresetSummary.fromJson({
        'name': 'value_v1',
        'description': 'Low PER + Low PBR + High ROE',
        'universe': 'KOSPI200',
        'rebalance_freq': 'QUARTERLY',
        'top_n': 20,
        'is_private': false,
        'is_grouped': false,
      });
      expect(p.isPrivate, isFalse);
      expect(p.isGrouped, isFalse);
    });

    test('missing/null universe, rebalance_freq, top_n do not throw', () {
      final p = StrategyPresetSummary.fromJson({
        'name': 'weird_preset',
        'is_private': false,
        'is_grouped': false,
      });
      expect(p.universe, isNull);
      expect(p.rebalanceFreq, isNull);
      expect(p.topN, isNull);
      expect(p.description, ''); // defaults, never null
    });
  });

  group('StrategyDefinitionDraft.fromFlatPreset', () {
    Map<String, dynamic> valueV1Json() => {
          'name': 'value_v1',
          'description': 'Low PER + Low PBR + High ROE, top-20 in KOSPI200',
          'universe': 'KOSPI200',
          'rebalance_freq': 'QUARTERLY',
          'start_date': '2016-01-01',
          'end_date': '2025-12-31',
          'top_n': 20,
          'factors': [
            {'factor': 'PER', 'weight': -1.0, 'transform': 'ZSCORE'},
            {'factor': 'PBR', 'weight': -0.8, 'transform': 'ZSCORE'},
            {'factor': 'ROE', 'weight': 1.0, 'transform': 'ZSCORE'},
          ],
          // Real YAML presets use lowercase field names — the engine
          // uppercases them internally, but the flat filter dropdown only
          // renders uppercase kFilterFields entries.
          'filters': [
            {'field': 'market_cap', 'op': 'GTE', 'value': 100000000000},
            {'field': 'trading_days_30d', 'op': 'GTE', 'value': 25},
          ],
        };

    test('maps name/universe/rebalance/topN/dates', () {
      final draft = StrategyDefinitionDraft.fromFlatPreset(valueV1Json());
      expect(draft.name, 'value_v1');
      expect(draft.universe, BacktestUniverse.kospi200);
      expect(draft.rebalanceFreq, BacktestRebalanceFreq.quarterly);
      expect(draft.topN, 20);
      expect(draft.startDate, DateTime(2016, 1, 1));
      expect(draft.endDate, DateTime(2025, 12, 31));
    });

    test('maps factors with weight and transform', () {
      final draft = StrategyDefinitionDraft.fromFlatPreset(valueV1Json());
      expect(draft.factors, hasLength(3));
      expect(draft.factors[0].factor, 'PER');
      expect(draft.factors[0].weight, -1.0);
      expect(draft.factors[0].transform, BacktestTransform.zscore);
    });

    test('uppercases lowercase YAML filter field names', () {
      final draft = StrategyDefinitionDraft.fromFlatPreset(valueV1Json());
      expect(draft.filters, hasLength(2));
      expect(draft.filters[0].field, 'MARKET_CAP');
      expect(draft.filters[1].field, 'TRADING_DAYS_30D');
      // Both fields must now resolve to a real dropdown item — this is
      // exactly what prevents the "value must match exactly one item"
      // Flutter assertion when the preset is loaded into the flat editor.
      for (final f in draft.filters) {
        expect(kFilterFields.contains(f.field), isTrue,
            reason: '${f.field} must be a valid kFilterFields entry after mapping');
      }
    });

    test('unknown universe/rebalance wire values fall back safely, not throw', () {
      final draft = StrategyDefinitionDraft.fromFlatPreset({
        ...valueV1Json(),
        'universe': 'KOSDAQ150', // valid on the backend, absent from the Flutter enum
        'rebalance_freq': 'WEEKLY', // not a real value at all
      });
      expect(draft.universe, BacktestUniverse.kospi200);
      expect(draft.rebalanceFreq, BacktestRebalanceFreq.monthly);
    });

    test('missing top_n defaults to 20 (the new standardized default)', () {
      final j = valueV1Json()..remove('top_n');
      final draft = StrategyDefinitionDraft.fromFlatPreset(j);
      expect(draft.topN, 20);
    });
  });

  group('BacktestFilterOp.fromWire', () {
    test('round-trips the four scalar ops', () {
      for (final op in [
        BacktestFilterOp.gt,
        BacktestFilterOp.gte,
        BacktestFilterOp.lt,
        BacktestFilterOp.lte,
      ]) {
        expect(BacktestFilterOp.fromWire(op.wire), op);
      }
    });

    test('BETWEEN falls back to GTE (never crashes the flat op dropdown)', () {
      expect(BacktestFilterOp.fromWire('BETWEEN'), BacktestFilterOp.gte);
    });

    test('unknown/null op falls back to GTE', () {
      expect(BacktestFilterOp.fromWire('NOT_A_REAL_OP'), BacktestFilterOp.gte);
      expect(BacktestFilterOp.fromWire(null), BacktestFilterOp.gte);
    });
  });

  group('default-option select-box constants', () {
    test('kTopNOptions matches the standardized {10,20,30,50}', () {
      expect(kTopNOptions, [10, 20, 30, 50]);
    });

    test('kPeriodPresets has 1/2/3/5-year windows plus a custom entry', () {
      final years = {for (final p in kPeriodPresets) p.key: p.years};
      expect(years['1Y'], 1);
      expect(years['2Y'], 2);
      expect(years['3Y'], 3);
      expect(years['5Y'], 5);
      expect(years['CUSTOM'], isNull);
    });

    test('kFilterPresets DEFAULT builds the two standard filters', () {
      final meta = kFilterPresets.firstWhere((p) => p.key == 'DEFAULT');
      final rules = meta.build!();
      expect(rules, hasLength(2));
      expect(rules[0].field, 'MARKET_CAP');
      expect(rules[0].op, BacktestFilterOp.gte);
      expect(rules[0].value, 100000000000.0);
      expect(rules[1].field, 'TRADING_DAYS_30D');
      expect(rules[1].value, 25.0);
    });

    test('kFilterPresets NONE builds an empty filter list', () {
      final meta = kFilterPresets.firstWhere((p) => p.key == 'NONE');
      expect(meta.build!(), isEmpty);
    });

    test('kFilterPresets CUSTOM has no build function (leaves rows as-is)', () {
      final meta = kFilterPresets.firstWhere((p) => p.key == 'CUSTOM');
      expect(meta.build, isNull);
    });
  });

  group('BuilderNotifier defaults + preset-select-box transitions', () {
    test('fresh state defaults to topN=20, 3Y period, DEFAULT filters', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(builderProvider.notifier);

      expect(notifier.state.draft.topN, 20);
      expect(notifier.state.periodPresetKey, '3Y');
      expect(notifier.state.filterPresetKey, 'DEFAULT');
      expect(notifier.state.draft.filters, hasLength(2));
      expect(notifier.state.isGroupedPresetMode, isFalse);
    });

    test('applyPeriodPreset(1Y) sets a ~1-year window ending today', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(builderProvider.notifier);

      notifier.applyPeriodPreset('1Y');
      final state = notifier.state;
      expect(state.periodPresetKey, '1Y');
      final spanDays = state.draft.endDate.difference(state.draft.startDate).inDays;
      // ~365 days, tolerant of leap years.
      expect(spanDays, inInclusiveRange(360, 366));
    });

    test('manually editing a date after a period preset falls back to CUSTOM', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(builderProvider.notifier);

      notifier.applyPeriodPreset('5Y');
      expect(notifier.state.periodPresetKey, '5Y');
      notifier.setStartDate(DateTime(2020, 1, 1));
      expect(notifier.state.periodPresetKey, 'CUSTOM');
      expect(notifier.state.draft.startDate, DateTime(2020, 1, 1));
    });

    test('applyFilterPreset(NONE) clears filters; manual edit falls back to CUSTOM', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(builderProvider.notifier);

      notifier.applyFilterPreset('NONE');
      expect(notifier.state.filterPresetKey, 'NONE');
      expect(notifier.state.draft.filters, isEmpty);

      notifier.addFilter();
      expect(notifier.state.filterPresetKey, 'CUSTOM');
      expect(notifier.state.draft.filters, hasLength(1));
    });

    test('setTopN updates the draft', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(builderProvider.notifier);

      notifier.setTopN(30);
      expect(notifier.state.draft.topN, 30);
    });

    test('isValid stays true for an empty-factors state once a groupedPreset is present', () {
      // Simulates the post-loadPreset(grouped) state without touching the
      // network: build a state directly and assert the isValid contract
      // BuilderScreen's FAB relies on.
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final notifier = container.read(builderProvider.notifier);

      // Flat mode with no factors must be invalid (existing contract).
      final noFactors = notifier.state.copyWith(
        draft: notifier.state.draft.copyWith(factors: []),
      );
      expect(noFactors.isValid, isFalse);

      // Grouped mode is inherently valid even with empty flat factors —
      // the raw preset (not the flat draft) is what gets submitted.
      final grouped = noFactors.copyWith(groupedPreset: {'name': 'qlab_alpha_v2'});
      expect(grouped.isValid, isTrue);
    });
  });
}
