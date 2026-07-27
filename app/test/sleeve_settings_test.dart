/// Test seed: AppSettings.fromJson parses the two-sleeve settings fields
/// (`etf_strategy_name` / `sleeve_etf_weight`, `.omc/plan/
/// 2026-07-25_two-sleeve-tax.md` T3/T11) with safe fallbacks for pre-T3
/// backends, plus the shared `sleeveWeightPct` helper that drives the
/// settings screen's slider label (and must never hand the Slider widget
/// an out-of-[0,1] value).
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/settings_api.dart';

Map<String, dynamic> _baseJson() => {
      'accounts': [],
      'default_drop_threshold_pct': 5.0,
      'telegram_chat_id': null,
      'telegram_token_masked': '',
      'llm_provider': 'openai',
      'llm_model': 'gpt-4o',
      'llm_api_key_masked': '',
      'llm_cache_ttl_hours': 24,
      'rating_strategy_name': 'value_v1',
    };

void main() {
  group('AppSettings.fromJson — sleeve fields', () {
    test('parses explicit etf_strategy_name + sleeve_etf_weight', () {
      final s = AppSettings.fromJson({
        ..._baseJson(),
        'etf_strategy_name': 'etf_rotation_kr',
        'sleeve_etf_weight': 0.4,
      });
      expect(s.etfStrategyName, 'etf_rotation_kr');
      expect(s.sleeveEtfWeight, 0.4);
    });

    test('falls back to etf_rotation_kr / 0.3 when absent (pre-T3 backend)', () {
      final s = AppSettings.fromJson(_baseJson());
      expect(s.etfStrategyName, 'etf_rotation_kr');
      expect(s.sleeveEtfWeight, 0.3);
    });

    test('falls back when fields are explicitly null', () {
      final s = AppSettings.fromJson({
        ..._baseJson(),
        'etf_strategy_name': null,
        'sleeve_etf_weight': null,
      });
      expect(s.etfStrategyName, 'etf_rotation_kr');
      expect(s.sleeveEtfWeight, 0.3);
    });

    test('clamps an out-of-range weight instead of crashing the Slider', () {
      final over = AppSettings.fromJson({..._baseJson(), 'sleeve_etf_weight': 1.5});
      final under = AppSettings.fromJson({..._baseJson(), 'sleeve_etf_weight': -0.2});
      expect(over.sleeveEtfWeight, 1.0);
      expect(under.sleeveEtfWeight, 0.0);
    });

    test('other fields still parse unaffected', () {
      final s = AppSettings.fromJson({
        ..._baseJson(),
        'etf_strategy_name': 'etf_rotation_kr',
        'sleeve_etf_weight': 0.3,
      });
      expect(s.ratingStrategyName, 'value_v1');
      expect(s.llmProvider, 'openai');
      expect(s.accounts, isEmpty);
      expect(s.toss, isNull);
    });
  });

  group('sleeveWeightPct — slider display rounding', () {
    test('30% ETF → (30, 70)', () {
      expect(sleeveWeightPct(0.3), (30, 70));
    });

    test('divisions-of-20 steps (5% each) round cleanly', () {
      expect(sleeveWeightPct(0.05), (5, 95));
      expect(sleeveWeightPct(0.65), (65, 35));
    });

    test('rounds to the nearest whole percent', () {
      expect(sleeveWeightPct(0.333), (33, 67));
    });

    test('0% and 100% edges', () {
      expect(sleeveWeightPct(0.0), (0, 100));
      expect(sleeveWeightPct(1.0), (100, 0));
    });

    test('clamps out-of-range input rather than producing a negative pct', () {
      expect(sleeveWeightPct(1.4), (100, 0));
      expect(sleeveWeightPct(-0.4), (0, 100));
    });
  });
}
