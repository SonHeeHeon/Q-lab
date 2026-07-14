/// Test seed: ReasonChip.labelFor / detailFor / colorFor map the backend's
/// structured trade `reason` (rule + extra keys) to Korean labels, compact
/// detail strings, and BUY/SELL-convention colors (매수=빨강, 매도=파랑).
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/shared/widgets/reason_chip.dart';

void main() {
  group('ReasonChip.labelFor', () {
    test('maps known rules to Korean labels', () {
      expect(ReasonChip.labelFor({'rule': 'REBALANCE_IN'}), '신규 편입');
      expect(ReasonChip.labelFor({'rule': 'REBALANCE_OUT'}), '리밸런스 제외');
      expect(ReasonChip.labelFor({'rule': 'STOP_LOSS'}), '손절');
      expect(ReasonChip.labelFor({'rule': 'TAKE_PROFIT'}), '익절');
      expect(ReasonChip.labelFor({'rule': 'BAND_TRIM'}), '비중 트림');
      expect(ReasonChip.labelFor({'rule': 'SCORE_EXIT'}), '점수 이탈');
      expect(ReasonChip.labelFor({'rule': 'SCORE_EXIT_REPLACE'}), '교체 편입');
      expect(ReasonChip.labelFor({'rule': 'REGIME_DERISK'}), '레짐 축소');
      expect(ReasonChip.labelFor({'rule': 'REGIME_RERISK'}), '레짐 복원');
    });

    test('is case-insensitive on the rule string', () {
      expect(ReasonChip.labelFor({'rule': 'stop_loss'}), '손절');
    });

    test('falls back to the raw rule string for unknown rules', () {
      expect(ReasonChip.labelFor({'rule': 'MYSTERY'}), 'MYSTERY');
    });

    test('falls back to a generic label when rule is missing/empty', () {
      expect(ReasonChip.labelFor({}), '제안');
      expect(ReasonChip.labelFor({'rule': ''}), '제안');
    });
  });

  group('ReasonChip.detailFor', () {
    test('REBALANCE_IN includes rank and score', () {
      final d = ReasonChip.detailFor(
          {'rule': 'REBALANCE_IN', 'rank': 8, 'score': 0.91});
      expect(d, contains('신규 편입'));
      expect(d, contains('순위 8'));
      expect(d, contains('0.91'));
    });

    test('REBALANCE_IN without score omits the score segment', () {
      final d = ReasonChip.detailFor({'rule': 'REBALANCE_IN', 'rank': 3});
      expect(d, '신규 편입 · 순위 3');
    });

    test('STOP_LOSS shows a signed negative percent return', () {
      final d = ReasonChip.detailFor({'rule': 'STOP_LOSS', 'return': -0.12});
      expect(d, '손절 · -12.0%');
    });

    test('TAKE_PROFIT shows a signed positive percent return', () {
      final d = ReasonChip.detailFor({'rule': 'TAKE_PROFIT', 'return': 0.31});
      expect(d, '익절 · +31.0%');
    });

    test('BAND_TRIM shows the threshold as a percent', () {
      final d =
          ReasonChip.detailFor({'rule': 'BAND_TRIM', 'threshold': 0.15});
      expect(d, '비중 트림 · 임계 15.0%');
    });

    test('SCORE_EXIT points at the stock that replaces it', () {
      final d = ReasonChip.detailFor(
          {'rule': 'SCORE_EXIT', 'replaced_by': '000660'});
      expect(d, '점수 이탈 → 000660');
    });

    test('SCORE_EXIT_REPLACE points back at the stock it replaces', () {
      final d = ReasonChip.detailFor(
          {'rule': 'SCORE_EXIT_REPLACE', 'replaces': '005930'});
      expect(d, '교체 편입 ← 005930');
    });

    test('REGIME_DERISK shows the exposure step-down', () {
      final d = ReasonChip.detailFor({
        'rule': 'REGIME_DERISK',
        'from_exposure': 1.0,
        'to_exposure': 0.4,
        'label': 'risk_off',
      });
      expect(d, '레짐 축소 100→40%');
    });

    test('REGIME_RERISK shows the exposure target', () {
      final d = ReasonChip.detailFor({
        'rule': 'REGIME_RERISK',
        'to_exposure': 0.8,
        'label': 'risk_on',
      });
      expect(d, '레짐 복원 →80%');
    });

    test('REBALANCE_OUT has no extra keys, so just the label', () {
      expect(ReasonChip.detailFor({'rule': 'REBALANCE_OUT'}), '리밸런스 제외');
    });

    test('missing expected extra keys falls back to the bare label', () {
      expect(ReasonChip.detailFor({'rule': 'STOP_LOSS'}), '손절');
    });

    test('tolerates Decimal-as-string numeric fields', () {
      final d = ReasonChip.detailFor({'rule': 'STOP_LOSS', 'return': '-0.12'});
      expect(d, '손절 · -12.0%');
    });
  });

  group('ReasonChip.colorFor', () {
    test('buy-ish rules use the BUY (red) hue', () {
      expect(ReasonChip.colorFor({'rule': 'REBALANCE_IN'}), Colors.redAccent);
      expect(ReasonChip.colorFor({'rule': 'SCORE_EXIT_REPLACE'}),
          Colors.redAccent);
      expect(
          ReasonChip.colorFor({'rule': 'REGIME_RERISK'}), Colors.redAccent);
    });

    test('sell-ish (and unknown) rules use the SELL (blue) hue', () {
      expect(ReasonChip.colorFor({'rule': 'STOP_LOSS'}), Colors.blueAccent);
      expect(ReasonChip.colorFor({'rule': 'TAKE_PROFIT'}), Colors.blueAccent);
      expect(ReasonChip.colorFor({'rule': 'BAND_TRIM'}), Colors.blueAccent);
      expect(ReasonChip.colorFor({'rule': 'SCORE_EXIT'}), Colors.blueAccent);
      expect(
          ReasonChip.colorFor({'rule': 'REGIME_DERISK'}), Colors.blueAccent);
      expect(ReasonChip.colorFor({'rule': 'MYSTERY'}), Colors.blueAccent);
    });
  });

  group('ReasonChip widget', () {
    testWidgets('renders the rule detail for a known rule', (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          body: ReasonChip(reason: {'rule': 'STOP_LOSS', 'return': -0.12}),
        ),
      ));
      expect(find.text('손절 · -12.0%'), findsOneWidget);
    });

    testWidgets('renders a neutral dash for a null reason', (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: ReasonChip(reason: null)),
      ));
      expect(find.text('—'), findsOneWidget);
    });

    testWidgets('renders a neutral dash when rule is absent', (tester) async {
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: ReasonChip(reason: {})),
      ));
      expect(find.text('—'), findsOneWidget);
    });
  });
}
