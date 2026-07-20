// Locks in the OHLC candle contract for the timeframe chart
// (stock_detail_screen.dart's _CandleChart):
//   - Candle.fromJson parses date/open/high/low/close/volume
//   - Candle.isUp reflects close>=open (drives up=red/down=blue coloring)
//   - mergeOlderCandles prepends an older `before:`-paged batch while
//     de-duplicating the inclusive boundary bar the backend returns again
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/stocks_api.dart';

void main() {
  group('Candle.fromJson', () {
    test('parses all OHLCV fields', () {
      final c = Candle.fromJson({
        'date': '2026-06-24',
        'open': 75000.0,
        'high': 76000.0,
        'low': 74800.0,
        'close': 75500.0,
        'volume': 12000000,
      });
      expect(c.date, DateTime.parse('2026-06-24'));
      expect(c.open, 75000.0);
      expect(c.high, 76000.0);
      expect(c.low, 74800.0);
      expect(c.close, 75500.0);
      expect(c.volume, 12000000);
    });

    test('missing volume parses as null rather than throwing', () {
      final c = Candle.fromJson({
        'date': '2026-06-24',
        'open': 100.0,
        'high': 101.0,
        'low': 99.0,
        'close': 100.5,
      });
      expect(c.volume, isNull);
    });

    test('isUp true when close >= open (red/up), false when close < open (blue/down)', () {
      final up = Candle.fromJson({
        'date': '2026-06-24',
        'open': 100.0,
        'high': 105.0,
        'low': 99.0,
        'close': 102.0,
      });
      final down = Candle.fromJson({
        'date': '2026-06-25',
        'open': 102.0,
        'high': 103.0,
        'low': 95.0,
        'close': 96.0,
      });
      final flat = Candle.fromJson({
        'date': '2026-06-26',
        'open': 96.0,
        'high': 97.0,
        'low': 95.0,
        'close': 96.0,
      });
      expect(up.isUp, isTrue);
      expect(down.isUp, isFalse);
      expect(flat.isUp, isTrue); // close == open treated as up, matches Candle.isUp contract
    });
  });

  // ── Pan paging: prepend older page + dedupe the inclusive boundary bar ────

  group('mergeOlderCandles', () {
    Candle candle(String date, {double close = 100.0}) => Candle.fromJson({
          'date': date,
          'open': close,
          'high': close,
          'low': close,
          'close': close,
        });

    test('prepends strictly-older bars in front of the current list', () {
      final current = [candle('2026-03-10'), candle('2026-03-11'), candle('2026-03-12')];
      final olderPage = [candle('2026-03-08'), candle('2026-03-09')];

      final merged = mergeOlderCandles(current, olderPage);

      expect(merged.map((c) => c.date.toIso8601String().substring(0, 10)), [
        '2026-03-08',
        '2026-03-09',
        '2026-03-10',
        '2026-03-11',
        '2026-03-12',
      ]);
    });

    test('dedupes the inclusive boundary bar the backend returns again', () {
      // `before=2026-03-10` is inclusive, so the backend's older page ends
      // on 2026-03-10 again — that duplicate must be dropped, not doubled.
      final current = [candle('2026-03-10'), candle('2026-03-11')];
      final olderPage = [candle('2026-03-08'), candle('2026-03-09'), candle('2026-03-10')];

      final merged = mergeOlderCandles(current, olderPage);

      expect(merged.length, 4);
      expect(merged.map((c) => c.date.toIso8601String().substring(0, 10)), [
        '2026-03-08',
        '2026-03-09',
        '2026-03-10',
        '2026-03-11',
      ]);
    });

    test('empty current list returns the older page as-is (first page load)', () {
      final olderPage = [candle('2026-03-08'), candle('2026-03-09')];
      final merged = mergeOlderCandles(const [], olderPage);
      expect(merged, olderPage);
    });

    test('older page with nothing new (reached start of history) leaves current unchanged', () {
      final current = [candle('2026-03-10'), candle('2026-03-11')];
      // Backend has no more history before this — echoes back only the
      // boundary bar (or an empty page); either way nothing new to add.
      final olderPage = [candle('2026-03-10')];

      final merged = mergeOlderCandles(current, olderPage);

      expect(merged, current);
    });
  });
}
