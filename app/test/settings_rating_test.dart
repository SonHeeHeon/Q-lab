/// Test seed: AppSettings.fromJson parses the ratings-batch strategy
/// preset (`rating_strategy_name`, Phase 4.6 T5/T8) and falls back to the
/// backend's own default (`DEFAULT_STRATEGY_NAME = "value_v1"`,
/// `backend/app/core/config.py`) when the backend hasn't shipped the field
/// yet or omits it.
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
    };

void main() {
  group('AppSettings.fromJson — rating_strategy_name', () {
    test('parses an explicit rating_strategy_name', () {
      final s = AppSettings.fromJson({
        ..._baseJson(),
        'rating_strategy_name': 'qlab_alpha_v2',
      });
      expect(s.ratingStrategyName, 'qlab_alpha_v2');
    });

    test('falls back to value_v1 when the field is absent (pre-T5 backend)', () {
      final s = AppSettings.fromJson(_baseJson());
      expect(s.ratingStrategyName, 'value_v1');
    });

    test('falls back to value_v1 when the field is explicitly null', () {
      final s = AppSettings.fromJson({
        ..._baseJson(),
        'rating_strategy_name': null,
      });
      expect(s.ratingStrategyName, 'value_v1');
    });

    test('other fields still parse unaffected', () {
      final s = AppSettings.fromJson({
        ..._baseJson(),
        'rating_strategy_name': 'value_v1',
      });
      expect(s.llmProvider, 'openai');
      expect(s.llmModel, 'gpt-4o');
      expect(s.accounts, isEmpty);
      expect(s.toss, isNull);
    });
  });
}
