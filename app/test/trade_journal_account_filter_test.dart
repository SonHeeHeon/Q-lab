// Locks in the trade journal's broker+account filter predicate
// (전체/모의/실전/ISA/토스). Toss trades carry broker="TOSS" and a null
// account_type (no KIS-style PAPER/REAL/ISA split); KIS trades carry
// broker="KIS" plus a non-null account_type.
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/presentation/trade_journal/trade_journal_controller.dart';

void main() {
  group('matchesAccountFilter', () {
    test('전체 (JournalFilter.all) matches every broker/account combination', () {
      expect(matchesAccountFilter('KIS', 'PAPER', JournalFilter.all), isTrue);
      expect(matchesAccountFilter('KIS', 'REAL', JournalFilter.all), isTrue);
      expect(matchesAccountFilter('KIS', 'ISA', JournalFilter.all), isTrue);
      expect(matchesAccountFilter('TOSS', null, JournalFilter.all), isTrue);
    });

    test('KIS filters match the selected account case-insensitively', () {
      expect(matchesAccountFilter('KIS', 'REAL', JournalFilter.real), isTrue);
      expect(matchesAccountFilter('kis', 'real', JournalFilter.real), isTrue);
      expect(matchesAccountFilter('Kis', 'Real', JournalFilter.real), isTrue);
    });

    test('KIS filters reject non-matching accounts', () {
      expect(matchesAccountFilter('KIS', 'PAPER', JournalFilter.real), isFalse);
      expect(matchesAccountFilter('KIS', 'ISA', JournalFilter.paper), isFalse);
    });

    test('KIS filters never match a Toss trade (null account_type)', () {
      expect(matchesAccountFilter('TOSS', null, JournalFilter.paper), isFalse);
      expect(matchesAccountFilter('TOSS', null, JournalFilter.real), isFalse);
      expect(matchesAccountFilter('TOSS', null, JournalFilter.isa), isFalse);
    });

    test('토스 filter matches only broker=="TOSS", case-insensitively', () {
      expect(matchesAccountFilter('TOSS', null, JournalFilter.toss), isTrue);
      expect(matchesAccountFilter('toss', null, JournalFilter.toss), isTrue);
      expect(matchesAccountFilter('KIS', 'REAL', JournalFilter.toss), isFalse);
    });

    test('a mixed broker/account list filters down to only the selected filter', () {
      final rows = [
        ('KIS', 'PAPER'),
        ('KIS', 'REAL'),
        ('KIS', 'ISA'),
        ('KIS', 'REAL'),
        ('TOSS', null),
      ];

      bool matches(JournalFilter f) =>
          rows.where((r) => matchesAccountFilter(r.$1, r.$2, f)).length ==
          switch (f) {
            JournalFilter.all => 5,
            JournalFilter.paper => 1,
            JournalFilter.real => 2,
            JournalFilter.isa => 1,
            JournalFilter.toss => 1,
          };

      for (final f in JournalFilter.values) {
        expect(matches(f), isTrue, reason: 'mismatch for $f');
      }
    });
  });
}
