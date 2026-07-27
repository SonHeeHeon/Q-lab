/// T7 wiring test: verifies the mock fixture layer added for
/// `/api/ratings*` produces payloads that `RatingsApi`'s real model
/// parsers accept, and that the resulting models render through
/// `RatingChip` the same way the search/detail/portfolio screens do.
///
/// The three screens (`stock_search_screen.dart`, `stock_detail_screen.dart`,
/// `portfolio_screen.dart`) are Riverpod-heavy `ConsumerWidget`s wired to
/// live Dio-backed providers (`stockSearchProvider`, `stockDetailProvider`,
/// `accountDetailProvider`/`unifiedPortfolioProvider`) plus go_router
/// navigation — pumping them in isolation would mean re-building most of
/// the app's provider graph with overrides, which no existing test in this
/// suite does (see `test/widget_test.dart`'s note on why it stays a smoke
/// test). Following that precedent, this file instead locks in the
/// mock-fixture -> model -> chip pipeline the screens all depend on.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/mock_fixtures.dart';
import 'package:qlab/data/api/ratings_api.dart';
import 'package:qlab/shared/widgets/rating_chip.dart';

void main() {
  group('MockFixtures /api/ratings*', () {
    test('GET /api/ratings parses into one OK/STRONG_BUY + one NO_DATA row', () {
      final fixture = MockFixtures.resolve('GET', '/api/ratings', const {});
      expect(fixture, isNotNull);
      final list = (fixture!.data as List)
          .map((e) => StockRating.fromJson(e as Map<String, dynamic>))
          .toList();
      expect(list, hasLength(2));

      final ok = list.firstWhere((r) => r.code == '005930');
      expect(ok.status, 'OK');
      expect(ok.buyGrade, 'STRONG_BUY');
      expect(RatingChip.buyLabelFor(ok.buyGrade!), '적극매수');

      final noData = list.firstWhere((r) => r.code == '035420');
      expect(noData.status, 'NO_DATA');
      expect(noData.buyGrade, isNull);
    });

    test('GET /api/ratings/positions parses a SELL_NOW row with a reason', () {
      final fixture =
          MockFixtures.resolve('GET', '/api/ratings/positions', const {});
      expect(fixture, isNotNull);
      final list = (fixture!.data as List)
          .map((e) => PositionRating.fromJson(e as Map<String, dynamic>))
          .toList();
      expect(list, hasLength(1));

      final p = list.single;
      expect(p.broker, 'KIS');
      expect(p.accountKey, 'REAL');
      expect(p.code, '035420');
      expect(p.sellGrade, 'SELL_NOW');
      expect(reasonText(p.reason), contains('손절'));
      expect(reasonText(p.reason), contains('-12.3%'));
    });

    test('GET /api/ratings/status parses scheduler + EOD/intraday markers', () {
      final fixture = MockFixtures.resolve('GET', '/api/ratings/status', const {});
      expect(fixture, isNotNull);
      final status =
          RatingStatus.fromJson(fixture!.data as Map<String, dynamic>);
      expect(status.schedulerRunning, isTrue);
      expect(status.eod?.storedCount, 120);
      expect(status.intraday?.finishedAt, isNotEmpty);
    });

    test('POST /api/ratings/compute echoes the requested code back with a grade', () {
      final fixture = MockFixtures.resolve(
        'POST',
        '/api/ratings/compute',
        {'code': '000660'},
      );
      expect(fixture, isNotNull);
      final rating =
          StockRating.fromJson(fixture!.data as Map<String, dynamic>);
      expect(rating.code, '000660');
      expect(rating.status, 'OK');
      expect(rating.buyGrade, isNotNull);
    });

    test('an unrelated path still resolves to null (no over-broad matching)', () {
      expect(MockFixtures.resolve('GET', '/api/watchlist', const {}), isNull);
    });
  });

  group('ratingsKey', () {
    test('sorts and dedupes codes into a deterministic CSV', () {
      expect(ratingsKey(['035420', '005930', '005930']), '005930,035420');
      expect(ratingsKey(['005930']), ratingsKey(['005930']));
    });
  });

  group('fixture rows render through RatingChip (search/portfolio wiring)', () {
    testWidgets('the OK/STRONG_BUY row renders a buy chip, not a muted dash',
        (tester) async {
      final fixture = MockFixtures.resolve('GET', '/api/ratings', const {})!;
      final ok = (fixture.data as List)
          .map((e) => StockRating.fromJson(e as Map<String, dynamic>))
          .firstWhere((r) => r.code == '005930');

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: RatingChip.buy(ok.buyGrade, status: ok.status)),
      ));
      expect(find.text('적극매수'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('the SELL_NOW position row renders a sell chip with a reason tooltip',
        (tester) async {
      final fixture =
          MockFixtures.resolve('GET', '/api/ratings/positions', const {})!;
      final pos = (fixture.data as List)
          .map((e) => PositionRating.fromJson(e as Map<String, dynamic>))
          .single;

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: RatingChip.sell(pos.sellGrade, reason: pos.reason, dense: true),
        ),
      ));
      expect(find.text('즉시매도'), findsOneWidget);
      expect(find.byType(Tooltip), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('a NO_DATA buy row never renders a chip in search (status-gated)',
        (tester) async {
      final fixture = MockFixtures.resolve('GET', '/api/ratings', const {})!;
      final noData = (fixture.data as List)
          .map((e) => StockRating.fromJson(e as Map<String, dynamic>))
          .firstWhere((r) => r.code == '035420');

      // Mirrors stock_search_screen.dart's _SearchTile gating: only render
      // when status == 'OK'. NO_DATA here must short-circuit to nothing.
      final shouldRender = noData.status.toUpperCase() == 'OK';
      expect(shouldRender, isFalse);
    });
  });
}
