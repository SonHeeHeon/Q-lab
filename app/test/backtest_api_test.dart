/// Test seed: TradeRecord.fromJson parses the structured `reason` object
/// the backend attaches to each backtest trade, and BacktestRunDetail
/// carries `trades[]` for PERSISTED runs (`GET /api/backtest/runs/{id}`).
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:qlab/data/api/backtest_api.dart';

Map<String, dynamic> _strategyJson() => {
      'name': 's1',
      'universe': 'KOSPI200',
      'rebalance_freq': 'MONTHLY',
      'factors': [],
      'filters': [],
      'top_n': 5,
      'start_date': '2025-01-01',
      'end_date': '2026-01-01',
    };

Map<String, dynamic> _metricsJson() => {
      'cagr': 0.12,
      'mdd': -0.2,
      'sharpe': 1.1,
      'win_rate': 0.55,
      'n_trades': 1,
    };

void main() {
  group('TradeRecord.fromJson', () {
    test('parses the reason object', () {
      final t = TradeRecord.fromJson({
        'date': '2026-03-10',
        'code': '005930',
        'side': 'SELL',
        'qty': 5,
        'price': 70000.0,
        'cash_flow': 349825.0,
        'reason': {'rule': 'STOP_LOSS', 'return': -0.12},
      });
      expect(t.code, '005930');
      expect(t.reason, isNotNull);
      expect(t.reason!['rule'], 'STOP_LOSS');
      expect(t.reason!['return'], -0.12);
    });

    test('tolerates a null/missing reason (older persisted runs)', () {
      final t = TradeRecord.fromJson({
        'date': '2026-03-10',
        'code': '005930',
        'side': 'BUY',
        'qty': 5,
        'price': 70000.0,
        'cash_flow': -350000.0,
      });
      expect(t.reason, isNull);
    });
  });

  group('BacktestRunDetail.fromJson', () {
    test('parses trades[] when present (persisted run)', () {
      final j = {
        'run_id': 'run-1',
        'metrics': _metricsJson(),
        'params': {'strategy': _strategyJson()},
        'trades': [
          {
            'date': '2026-03-10',
            'code': '005930',
            'side': 'BUY',
            'qty': 5,
            'price': 70000.0,
            'cash_flow': -350000.0,
            'reason': {'rule': 'REBALANCE_IN', 'rank': 8, 'score': 0.91},
          },
        ],
      };
      final detail = BacktestRunDetail.fromJson(j);
      expect(detail.trades, hasLength(1));
      expect(detail.trades.first.code, '005930');
      expect(detail.trades.first.reason!['rule'], 'REBALANCE_IN');
    });

    test('defaults to an empty list when trades is absent (older runs)', () {
      final j = {
        'run_id': 'run-2',
        'metrics': _metricsJson(),
        'params': {'strategy': _strategyJson()},
      };
      final detail = BacktestRunDetail.fromJson(j);
      expect(detail.trades, isEmpty);
    });
  });
}
