/// Smoke test for the Q-Lab root widget. The full integration test
/// suite lives in sibling files (parse_utils_test.dart,
/// fromwire_fallback_test.dart, builder_factor_guard_test.dart).
///
/// We don't pumpWidget the full QLabApp here because it needs a
/// SharedPreferences override at the ProviderScope level and would
/// also kick off the Dio HTTP client. Real widget tests will land in
/// V1.2 alongside golden tests for empty states.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/parse_utils.dart';

void main() {
  test('smoke: parse_utils module loads', () {
    expect(safeDouble(1.0), 1.0);
  });
}
