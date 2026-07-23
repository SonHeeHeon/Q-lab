// Locks in the HeatmapMarket wire contract, including the NASDAQ100
// addition — the SegmentedButton sends `market.wire` straight to the
// backend's `GET /api/heatmap?market=...` query param, so a typo here
// would silently break the US heatmap toggle.
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/heatmap_api.dart';

void main() {
  group('HeatmapMarket', () {
    test('wire values match backend contract', () {
      expect(HeatmapMarket.kospi.wire, 'KOSPI');
      expect(HeatmapMarket.kosdaq.wire, 'KOSDAQ');
      expect(HeatmapMarket.nasdaq100.wire, 'NASDAQ100');
    });

    test('exactly three markets, including nasdaq100', () {
      expect(HeatmapMarket.values.length, 3);
      expect(HeatmapMarket.values, contains(HeatmapMarket.nasdaq100));
    });
  });

  group('isUsHeatmapMarket', () {
    test('true for NASDAQ100, case-insensitive', () {
      expect(isUsHeatmapMarket('NASDAQ100'), isTrue);
      expect(isUsHeatmapMarket('nasdaq100'), isTrue);
      expect(isUsHeatmapMarket('Nasdaq100'), isTrue);
    });

    test('false for KR markets', () {
      expect(isUsHeatmapMarket('KOSPI'), isFalse);
      expect(isUsHeatmapMarket('KOSDAQ'), isFalse);
      expect(isUsHeatmapMarket(''), isFalse);
    });
  });
}
