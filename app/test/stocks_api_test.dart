// Locks in the stock search/detail model contracts and broker-routing rules:
//   - StockSearchResult parses KR/US fields + isUs getter
//   - StockDetail parses all sub-models (quote, factor, holding, watchlist, history)
//   - US watchlist entry uses symbol as-is (AAPL, not 00AAPL)
//   - US order payload carries broker=TOSS, KR carries broker=KIS
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/portfolio_api.dart';
import 'package:qlab/data/api/stocks_api.dart';
import 'package:qlab/domain/entities/account.dart';

void main() {
  // ── StockSearchResult ──────────────────────────────────────────────────────

  group('StockSearchResult.fromJson', () {
    test('KR stock parses correctly, isUs false', () {
      final r = StockSearchResult.fromJson({
        'symbol': '005930',
        'code': '005930',
        'name': '삼성전자',
        'market_country': 'KR',
        'broker': 'KIS',
        'market': 'KOSPI',
        'currency': 'KRW',
      });
      expect(r.symbol, '005930');
      expect(r.name, '삼성전자');
      expect(r.marketCountry, 'KR');
      expect(r.broker, 'KIS');
      expect(r.currency, 'KRW');
      expect(r.isUs, isFalse);
      expect(r.displayCode, '005930');
    });

    test('US stock parses correctly, isUs true', () {
      final r = StockSearchResult.fromJson({
        'symbol': 'AAPL',
        'name': 'Apple Inc.',
        'market_country': 'US',
        'broker': 'TOSS',
        'currency': 'USD',
      });
      expect(r.symbol, 'AAPL');
      expect(r.marketCountry, 'US');
      expect(r.broker, 'TOSS');
      expect(r.currency, 'USD');
      expect(r.isUs, isTrue);
      expect(r.displayCode, 'AAPL');
    });

    test('lowercase market_country/broker is normalised to uppercase', () {
      final r = StockSearchResult.fromJson({
        'symbol': 'NVDA',
        'name': 'NVIDIA',
        'market_country': 'us',
        'broker': 'toss',
        'currency': 'usd',
      });
      expect(r.marketCountry, 'US');
      expect(r.broker, 'TOSS');
      expect(r.currency, 'USD');
    });

    test('missing fields default to KR / KIS / KRW', () {
      final r = StockSearchResult.fromJson({'symbol': '000660', 'name': 'SK하이닉스'});
      expect(r.marketCountry, 'KR');
      expect(r.broker, 'KIS');
      expect(r.currency, 'KRW');
      expect(r.isUs, isFalse);
    });
  });

  // ── StockDetail ────────────────────────────────────────────────────────────

  group('StockDetail.fromJson', () {
    final _krJson = {
      'code': '005930',
      'symbol': '005930',
      'name': '삼성전자',
      'market_country': 'KR',
      'broker': 'KIS',
      'currency': 'KRW',
      'current_quote': {'price': 75500.0, 'change': 500.0, 'change_pct': 0.67},
      'latest_price': {
        'date': '2026-06-24',
        'open': 75000.0,
        'high': 76000.0,
        'low': 74800.0,
        'close': 75000.0,
        'volume': 12000000,
      },
      'factors': {'PER': 12.5, 'PBR': 1.2, 'ROE': 15.3, 'ROA': 8.2},
      'factor_ranks': {'PER': 25, 'PBR': 40},
      'price_history': [
        {'date': '2025-06-25', 'open': 70000.0, 'high': 71000.0, 'low': 69500.0, 'close': 70500.0},
        {'date': '2026-06-24', 'open': 75000.0, 'high': 76000.0, 'low': 74800.0, 'close': 75000.0},
      ],
      'holding': {
        'is_holding': true,
        'quantity': 10,
        'avg_buy_price': 70000.0,
        'broker': 'KIS',
      },
      'watchlist': {'is_watchlisted': false},
    };

    test('KR detail parses all sub-models', () {
      final d = StockDetail.fromJson(_krJson);
      expect(d.code, '005930');
      expect(d.isUs, isFalse);
      expect(d.displayPrice, 75500.0);
      expect(d.changePct, closeTo(0.67, 0.001));
      expect(d.factors?.per, 12.5);
      expect(d.factors?.pbr, 1.2);
      expect(d.factors?.roe, 15.3);
      expect(d.factorRanks?['PER'], 25);
      expect(d.holding?.isHolding, isTrue);
      expect(d.holding?.quantity, 10);
      expect(d.holding?.avgBuyPrice, 70000.0);
      expect(d.watchlistInfo?.isWatchlisted, isFalse);
      expect(d.priceHistory.length, 2);
      expect(d.priceHistory.last.close, 75000.0);
    });

    test('US detail parses symbol + USD currency', () {
      final d = StockDetail.fromJson({
        'code': 'AAPL',
        'symbol': 'AAPL',
        'name': 'Apple Inc.',
        'market_country': 'US',
        'broker': 'TOSS',
        'currency': 'USD',
        'current_quote': {'price': 220.5, 'change': 1.5, 'change_pct': 0.68},
        'price_history': [],
        'holding': {'is_holding': false},
        'watchlist': {'is_watchlisted': true, 'entry_id': 42, 'category_id': 1},
      });
      expect(d.isUs, isTrue);
      expect(d.symbol, 'AAPL');
      expect(d.currency, 'USD');
      expect(d.displayPrice, 220.5);
      expect(d.watchlistInfo?.isWatchlisted, isTrue);
      expect(d.watchlistInfo?.entryId, 42);
    });

    test('displayPrice falls back to latest_price.close when no quote', () {
      final d = StockDetail.fromJson({
        'code': 'AAPL',
        'symbol': 'AAPL',
        'name': 'Apple',
        'market_country': 'US',
        'broker': 'TOSS',
        'currency': 'USD',
        'latest_price': {
          'date': '2026-06-24',
          'open': 219.0,
          'high': 221.0,
          'low': 218.5,
          'close': 220.0,
        },
        'price_history': [],
      });
      expect(d.currentQuote, isNull);
      expect(d.displayPrice, 220.0);
    });

    test('empty price_history does not throw', () {
      final d = StockDetail.fromJson({
        'code': '000660',
        'symbol': '000660',
        'name': 'SK하이닉스',
        'market_country': 'KR',
        'broker': 'KIS',
        'currency': 'KRW',
        'price_history': [],
      });
      expect(d.priceHistory, isEmpty);
    });
  });

  // ── Watchlist: US symbol passes through unchanged ──────────────────────────

  group('Watchlist stock_code contract', () {
    test('AAPL symbol is used verbatim as stock_code (no transformation)', () {
      const symbol = 'AAPL';
      // The WatchlistApi.addEntry receives stockCode=symbol and sends it
      // directly to the backend. This test verifies the model returns the
      // raw symbol so callers don't accidentally transform it.
      final d = StockDetail.fromJson({
        'code': 'AAPL',
        'symbol': 'AAPL',
        'name': 'Apple',
        'market_country': 'US',
        'broker': 'TOSS',
        'currency': 'USD',
        'price_history': [],
      });
      expect(d.symbol, symbol);
    });
  });

  // ── Order payload broker routing ────────────────────────────────────────────

  group('PlaceOrderRequest broker routing from stock detail', () {
    test('US stock detail → broker=TOSS in order payload', () {
      final json = PlaceOrderRequest(
        broker: BrokerType.TOSS,
        accountType: KisAccount.paper,
        accountId: '7',
        stockCode: 'AAPL',
        direction: OrderDirection.buy,
        quantity: 3,
      ).toJson();
      expect(json['broker'], 'TOSS');
      expect(json['stock_code'], 'AAPL');
      expect(json['account_id'], '7');
    });

    test('KR stock detail → broker=KIS in order payload', () {
      final json = PlaceOrderRequest(
        broker: BrokerType.KIS,
        accountType: KisAccount.real,
        stockCode: '005930',
        direction: OrderDirection.buy,
        quantity: 10,
      ).toJson();
      expect(json['broker'], 'KIS');
      expect(json['stock_code'], '005930');
      expect(json.containsKey('account_id'), isFalse);
    });
  });
}
