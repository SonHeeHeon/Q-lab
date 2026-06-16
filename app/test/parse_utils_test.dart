/// Test seed: validates the centralized JSON-value coercion helpers.
/// These cover the historical bug where Pydantic Decimal strings like
/// "0E-8" or invalid strings like "N/A" were silently coerced to 0.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/parse_utils.dart';

void main() {
  group('safeDouble', () {
    test('parses int and double directly', () {
      expect(safeDouble(42), 42.0);
      expect(safeDouble(3.14), 3.14);
    });

    test('parses numeric strings including scientific notation', () {
      expect(safeDouble('10000000'), 10000000.0);
      expect(safeDouble('0E-8'), 0.0);
      expect(safeDouble('-1.5'), -1.5);
    });

    test('returns fallback on null / empty / malformed', () {
      expect(safeDouble(null), 0.0);
      expect(safeDouble(''), 0.0);
      expect(safeDouble('N/A', warnOnFallback: false), 0.0);
      expect(safeDouble('--', warnOnFallback: false), 0.0);
      expect(safeDouble({}, warnOnFallback: false), 0.0);
    });

    test('custom fallback is honored', () {
      expect(safeDouble('bad', fallback: -1, warnOnFallback: false), -1.0);
    });
  });

  group('safeDoubleOrNull', () {
    test('distinguishes missing from zero', () {
      expect(safeDoubleOrNull(null), isNull);
      expect(safeDoubleOrNull(''), isNull);
      expect(safeDoubleOrNull('0'), 0.0);
    });

    test('returns null on malformed', () {
      expect(safeDoubleOrNull('N/A'), isNull);
    });
  });

  group('safeInt', () {
    test('parses int / num / string', () {
      expect(safeInt(42), 42);
      expect(safeInt(3.7), 3);
      expect(safeInt('123'), 123);
      expect(safeInt('45.9'), 45);
    });

    test('falls back on garbage', () {
      expect(safeInt(null), 0);
      expect(safeInt('garbage', warnOnFallback: false), 0);
    });
  });
}
