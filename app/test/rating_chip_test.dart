/// Test seed: RatingChip renders the buy-axis (`StockRating.buyGrade`) and
/// sell-axis (`PositionRating.sellGrade`) Korean labels with a non-null
/// color, handles NO_DATA/UNSUPPORTED/null defensively (never throws), and
/// `reasonText` maps a sell reason's `rule` to a Korean sentence.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/shared/widgets/rating_chip.dart';

void main() {
  group('RatingChip.buyLabelFor / buyColorFor', () {
    const grades = [
      'STRONG_BUY',
      'BUY',
      'NEUTRAL',
      'REDUCE',
      'AVOID',
    ];
    const labels = {
      'STRONG_BUY': '적극매수',
      'BUY': '매수',
      'NEUTRAL': '중립',
      'REDUCE': '비중축소',
      'AVOID': '매수회피',
    };

    for (final grade in grades) {
      test('$grade maps to a Korean label with a non-null color', () {
        expect(RatingChip.buyLabelFor(grade), labels[grade]);
        expect(RatingChip.buyColorFor(grade), isNotNull);
      });
    }

    test('is case-insensitive', () {
      expect(RatingChip.buyLabelFor('strong_buy'), '적극매수');
    });

    test('falls back to the raw grade string for an unknown grade', () {
      expect(RatingChip.buyLabelFor('MYSTERY'), 'MYSTERY');
      expect(RatingChip.buyColorFor('MYSTERY'), isNotNull);
    });
  });

  group('RatingChip.sellLabelFor / sellColorFor', () {
    const grades = ['SELL_NOW', 'SELL', 'WATCH', 'HOLD', 'KEEP'];
    const labels = {
      'SELL_NOW': '즉시매도',
      'SELL': '매도',
      'WATCH': '관망',
      'HOLD': '보유',
      'KEEP': '유지',
    };

    for (final grade in grades) {
      test('$grade maps to a Korean label with a non-null color', () {
        expect(RatingChip.sellLabelFor(grade), labels[grade]);
        expect(RatingChip.sellColorFor(grade), isNotNull);
      });
    }

    test('is case-insensitive', () {
      expect(RatingChip.sellLabelFor('sell_now'), '즉시매도');
    });

    test('falls back to the raw grade string for an unknown grade', () {
      expect(RatingChip.sellLabelFor('MYSTERY'), 'MYSTERY');
      expect(RatingChip.sellColorFor('MYSTERY'), isNotNull);
    });
  });

  group('RatingChip.buy widget', () {
    testWidgets('renders each buy grade\'s Korean label', (tester) async {
      for (final entry in const {
        'STRONG_BUY': '적극매수',
        'BUY': '매수',
        'NEUTRAL': '중립',
        'REDUCE': '비중축소',
        'AVOID': '매수회피',
      }.entries) {
        await tester.pumpWidget(MaterialApp(
          home: Scaffold(body: RatingChip.buy(entry.key)),
        ));
        expect(find.text(entry.value), findsOneWidget,
            reason: 'grade ${entry.key}');
      }
    });

    testWidgets('NO_DATA renders a muted dash and does not throw',
        (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          body: RatingChip.buy(null, status: 'NO_DATA', dense: true),
        ),
      ));
      expect(find.text('—'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('NO_DATA renders the long label when not dense',
        (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: RatingChip.buy(null, status: 'NO_DATA')),
      ));
      expect(find.text('데이터 없음'), findsOneWidget);
    });

    testWidgets('UNSUPPORTED renders 미지원', (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          body: RatingChip.buy(null, status: 'UNSUPPORTED'),
        ),
      ));
      expect(find.text('미지원'), findsOneWidget);
    });

    testWidgets('null buy_grade with status OK renders a dash, not a crash',
        (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: RatingChip.buy(null)),
      ));
      expect(find.text('—'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('RatingChip.sell widget', () {
    testWidgets('renders each sell grade\'s Korean label', (tester) async {
      for (final entry in const {
        'SELL_NOW': '즉시매도',
        'SELL': '매도',
        'WATCH': '관망',
        'HOLD': '보유',
        'KEEP': '유지',
      }.entries) {
        await tester.pumpWidget(MaterialApp(
          home: Scaffold(body: RatingChip.sell(entry.key)),
        ));
        expect(find.text(entry.value), findsOneWidget,
            reason: 'grade ${entry.key}');
      }
    });

    testWidgets('wraps the chip in a Tooltip when a reason is given',
        (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          body: RatingChip.sell(
            'SELL_NOW',
            reason: {'rule': 'STOP_LOSS', 'pl_rate': -12.3},
          ),
        ),
      ));
      expect(find.byType(Tooltip), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('renders without a Tooltip when no reason is given',
        (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: RatingChip.sell('KEEP')),
      ));
      expect(find.byType(Tooltip), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });

  group('reasonText', () {
    test('STOP_LOSS includes 손절 and the signed pl_rate', () {
      final t = reasonText({'rule': 'STOP_LOSS', 'pl_rate': -12.3});
      expect(t, contains('손절'));
      expect(t, contains('-12.3%'));
    });

    test('TAKE_PROFIT includes 목표가', () {
      final t = reasonText({'rule': 'TAKE_PROFIT', 'pl_rate': 31.0});
      expect(t, contains('목표가'));
      expect(t, contains('+31.0%'));
    });

    test('SCORE_PERCENTILE includes 점수 and the percentile', () {
      final t = reasonText({
        'rule': 'SCORE_PERCENTILE',
        'percentile': 0.18,
        'weakest_group': 'Value',
      });
      expect(t, contains('점수'));
      expect(t, contains('18%'));
      expect(t, contains('Value'));
    });

    test('BAND_TRIM includes 비중', () {
      final t = reasonText({'rule': 'BAND_TRIM', 'weight': 0.21});
      expect(t, contains('비중'));
      expect(t, contains('21.0%'));
    });

    test('NO_DATA includes 데이터 부족 and does not throw on a bare reason', () {
      expect(reasonText({'rule': 'NO_DATA'}), contains('데이터 부족'));
    });

    test('missing rule falls back to a generic sentence without throwing', () {
      expect(reasonText({}), isNotEmpty);
    });
  });
}
