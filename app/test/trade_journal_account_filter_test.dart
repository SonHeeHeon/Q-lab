// Locks in the trade journal's account filter predicate (전체/모의/실전/ISA).
// The journal only ever contains KIS-executed trades (Toss executions
// aren't recorded in the trades table), so the filter's universe is
// exactly KisAccount.values — this test also guards against someone later
// wiring in a Toss option that would always be empty.
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/domain/entities/account.dart';
import 'package:qlab/presentation/trade_journal/trade_journal_controller.dart';

void main() {
  group('matchesAccountFilter', () {
    test('null filter (전체) matches every account_type', () {
      for (final wire in ['PAPER', 'REAL', 'ISA', 'paper', 'unexpected', '']) {
        expect(matchesAccountFilter(wire, null), isTrue);
      }
    });

    test('matches the selected account case-insensitively', () {
      expect(matchesAccountFilter('REAL', KisAccount.real), isTrue);
      expect(matchesAccountFilter('real', KisAccount.real), isTrue);
      expect(matchesAccountFilter('Real', KisAccount.real), isTrue);
    });

    test('rejects non-matching accounts', () {
      expect(matchesAccountFilter('PAPER', KisAccount.real), isFalse);
      expect(matchesAccountFilter('ISA', KisAccount.paper), isFalse);
    });

    test('a mixed-account list filters down to only the selected account', () {
      final rows = ['PAPER', 'REAL', 'ISA', 'REAL', 'paper'];

      expect(
        rows.where((r) => matchesAccountFilter(r, KisAccount.real)).toList(),
        ['REAL', 'REAL'],
      );
      expect(
        rows.where((r) => matchesAccountFilter(r, KisAccount.paper)).toList(),
        ['PAPER', 'paper'],
      );
      expect(
        rows.where((r) => matchesAccountFilter(r, KisAccount.isa)).toList(),
        ['ISA'],
      );
      // null (전체) shows everything, unfiltered.
      expect(
        rows.where((r) => matchesAccountFilter(r, null)).toList(),
        rows,
      );
    });
  });
}
