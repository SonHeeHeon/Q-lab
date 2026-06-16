/// Test seed: validates that domain enums survive unknown wire values
/// without throwing (was a top-3 BLOCKING bug — backend additions used
/// to crash the entire Home/Alerts screens).
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/domain/entities/account.dart';
import 'package:qlab/domain/entities/alert.dart';

void main() {
  group('KisAccount.fromWire', () {
    test('round-trips known values', () {
      for (final acc in KisAccount.values) {
        expect(KisAccount.fromWire(acc.wire), acc);
        expect(KisAccount.fromWire(acc.wire.toLowerCase()), acc);
      }
    });

    test('unknown wire falls back to PAPER (safe default)', () {
      expect(KisAccount.fromWire('FUTURES'), KisAccount.paper);
      expect(KisAccount.fromWire('REAL_ISA'), KisAccount.paper);
      expect(KisAccount.fromWire(''), KisAccount.paper);
    });
  });

  group('AlertCondition.fromWire', () {
    test('round-trips known values', () {
      for (final c in AlertCondition.values) {
        expect(AlertCondition.fromWire(c.wire), c);
      }
    });

    test('unknown wire falls back to priceAbove', () {
      expect(AlertCondition.fromWire('GAP_UP'), AlertCondition.priceAbove);
      expect(AlertCondition.fromWire('whatever'), AlertCondition.priceAbove);
    });
  });
}
