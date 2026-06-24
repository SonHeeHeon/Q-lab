// Locks in the multi-currency portfolio contracts:
//   - positions parse currency / market_country (KR vs US split)
//   - portfolio parses fx_rate / fx_as_of
//   - account summary parses cash_krw / cash_usd with cash_balance fallback
//   - money helpers convert USD→KRW and degrade to '--' without a rate.
import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/portfolio_api.dart';
import 'package:qlab/shared/format/money.dart';

void main() {
  group('UnifiedPosition currency / market_country', () {
    test('US position parses currency + market_country, isUs true', () {
      final p = UnifiedPosition.fromJson({
        'broker': 'TOSS',
        'stock_code': 'AAPL',
        'name': 'Apple',
        'quantity': 3,
        'avg_buy_price': 100.0,
        'current_price': 123.45,
        'currency': 'usd',
        'market_country': 'us',
      });
      expect(p.currency, 'USD');
      expect(p.marketCountry, 'US');
      expect(p.isUs, isTrue);
    });

    test('missing fields default to KRW / KR', () {
      final p = UnifiedPosition.fromJson({
        'broker': 'KIS',
        'stock_code': '005930',
        'quantity': 10,
        'avg_buy_price': 70000,
      });
      expect(p.currency, 'KRW');
      expect(p.marketCountry, 'KR');
      expect(p.isUs, isFalse);
    });
  });

  group('UnifiedPortfolio fx fields', () {
    test('parses fx_rate + fx_as_of', () {
      final pf = UnifiedPortfolio.fromJson({
        'as_of': '2026-06-24T01:00:00+09:00',
        'total_value': '1000',
        'total_pl': '0',
        'total_pl_pct': '0',
        'accounts': [],
        'positions': [],
        'fx_rate': 1380.5,
        'fx_as_of': '2026-06-24T00:59:00+09:00',
      });
      expect(pf.fxRate, 1380.5);
      expect(pf.fxAsOf, isNotNull);
    });

    test('fxRate null when absent', () {
      final pf = UnifiedPortfolio.fromJson({
        'as_of': '2026-06-24T01:00:00+09:00',
        'total_value': '0',
        'total_pl': '0',
        'total_pl_pct': '0',
        'accounts': [],
        'positions': [],
      });
      expect(pf.fxRate, isNull);
    });
  });

  group('UnifiedAccountSummary cash split', () {
    test('parses cash_krw + cash_usd', () {
      final a = UnifiedAccountSummary.fromJson({
        'broker': 'TOSS',
        'account_id': '7',
        'total_value': '14310000',
        'cash_balance': '500000',
        'total_pl': '0',
        'total_pl_pct': '0',
        'cash_krw': '500000',
        'cash_usd': '1250.00',
      });
      expect(a.cashKrw, 500000);
      expect(a.cashUsd, 1250.0);
    });

    test('cashKrw falls back to cash_balance when split absent', () {
      final a = UnifiedAccountSummary.fromJson({
        'broker': 'KIS',
        'account_type': 'REAL',
        'total_value': '38000000',
        'cash_balance': '3200000',
        'total_pl': '0',
        'total_pl_pct': '0',
      });
      expect(a.cashKrw, 3200000);
      expect(a.cashUsd, isNull);
    });
  });

  group('money helpers', () {
    test('usdToKrw converts with rate, null without', () {
      expect(usdToKrw(100, 1380), 138000);
      expect(usdToKrw(100, null), isNull);
    });

    test('krwFromNative converts USD and degrades to -- without rate', () {
      expect(krwFromNative(100, 'USD', 1380), '₩138,000');
      expect(krwFromNative(100, 'USD', null), '--');
      expect(krwFromNative(5000, 'KRW', null), '₩5,000');
    });

    test('formatNative picks symbol by currency', () {
      expect(usdFmt.format(123.45), '\$123.45');
      expect(formatNative(123.45, 'USD'), '\$123.45');
    });
  });
}
