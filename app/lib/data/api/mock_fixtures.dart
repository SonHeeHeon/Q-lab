/// File: app/lib/data/api/mock_fixtures.dart
///
/// Centralized mock JSON for the Flutter app. Lookup table keyed by
/// `METHOD path`. Returns the inner `data` object only; the
/// [MockInterceptor] wraps it in the API envelope.
///
/// Keep these fixtures shaped *exactly* like the real backend response
/// per `PROJECT_BLUEPRINT.md §8`. When the real backend ships, the only
/// thing that needs to flip is `Env.useMock`.
library;

class MockFixture {
  const MockFixture({required this.data, this.statusCode = 200});
  final Object data;
  final int statusCode;
}

class MockFixtures {
  const MockFixtures._();

  static MockFixture? resolve(
    String method,
    String path,
    Map<String, dynamic> query,
  ) {
    final key = '${method.toUpperCase()} $path';

    // On-demand compute echoes the requested code back with an OK grade —
    // dynamic (query-dependent), so it can't live in the static _table.
    if (key == 'POST /api/ratings/compute') {
      return MockFixture(data: _ratingCompute(query['code']?.toString() ?? ''));
    }

    final fixture = _table[key];
    if (fixture != null) return fixture;

    // Pattern matches (with path params)
    if (key.startsWith('GET /api/portfolio/') && !key.contains('history')) {
      return MockFixture(data: _portfolioSingleAccount(path.split('/').last));
    }
    return null;
  }

  static final Map<String, MockFixture> _table = {
    'GET /api/portfolio': MockFixture(data: _portfolioUnified),
    'GET /api/alerts': MockFixture(data: _alerts),
    'GET /api/ratings': MockFixture(data: _ratings),
    'GET /api/ratings/positions': MockFixture(data: _positionRatings),
    'GET /api/ratings/status': MockFixture(data: _ratingStatus),
  };

  // ---------------------------------------------------------------------------
  // Fixtures
  // ---------------------------------------------------------------------------

  static final Map<String, dynamic> _portfolioUnified = {
    'as_of': '2026-05-27T09:00:00+09:00',
    'total_value': 53234500,
    'total_pl': 1234500,
    'total_pl_pct': 2.32,
    'accounts': [
      {
        'account_type': 'PAPER',
        'total_value': 12340000,
        'cash_balance': 3400000,
        'total_pl': 234000,
        'total_pl_pct': 1.93,
      },
      {
        'account_type': 'REAL',
        'total_value': 30894500,
        'cash_balance': 1200000,
        'total_pl': 894500,
        'total_pl_pct': 2.98,
      },
      {
        'account_type': 'ISA',
        'total_value': 10000000,
        'cash_balance': 500000,
        'total_pl': 106000,
        'total_pl_pct': 1.07,
      },
    ],
    'positions': [
      {
        'account_type': 'REAL',
        'stock_code': '035420',
        'stock_name': 'NAVER',
        'quantity': 10,
        'avg_buy_price': 185000.0,
        'current_price': 191000.0,
      },
      {
        'account_type': 'REAL',
        'stock_code': '035720',
        'stock_name': '카카오',
        'quantity': 30,
        'avg_buy_price': 47000.0,
        'current_price': 48300.0,
      },
      {
        'account_type': 'PAPER',
        'stock_code': '000660',
        'stock_name': 'SK하이닉스',
        'quantity': 5,
        'avg_buy_price': 168000.0,
        'current_price': 165500.0,
      },
      {
        'account_type': 'PAPER',
        'stock_code': '005930',
        'stock_name': '삼성전자',
        'quantity': 20,
        'avg_buy_price': 72500.0,
        'current_price': 75500.0,
      },
    ],
    'market_status': {
      'kospi': 'OPEN',
      'kospi_index': 2740.21,
      'kospi_change_pct': 0.42,
      'kosdaq': 'OPEN',
      'kosdaq_index': 870.55,
      'kosdaq_change_pct': -0.18,
    },
  };

  static Map<String, dynamic> _portfolioSingleAccount(String accountType) => {
        'account_type': accountType.toUpperCase(),
        'total_value': 12340000,
        'cash_balance': 3400000,
        'positions': [
          {
            'account_type': accountType.toUpperCase(),
            'stock_code': '005930',
            'stock_name': '삼성전자',
            'quantity': 20,
            'avg_buy_price': 72500.0,
            'current_price': 75500.0,
          },
        ],
      };

  // ---------------------------------------------------------------------------
  // Ratings (T7) — buy-axis batch, sell-axis positions, scheduler status,
  // on-demand compute. Shapes mirror `RatingsApi`'s `fromJson` factories
  // exactly (`app/lib/data/api/ratings_api.dart`).
  // ---------------------------------------------------------------------------

  /// `GET /api/ratings` — one OK/STRONG_BUY row (005930, matches the
  /// portfolio fixture's 삼성전자 PAPER holding) + one NO_DATA row (035420,
  /// matches the REAL 홀딩 NAVER position so the detail screen's "등급 계산"
  /// path is exercisable under mock too).
  static final List<Map<String, dynamic>> _ratings = [
    {
      'code': '005930',
      'status': 'OK',
      'buy_grade': 'STRONG_BUY',
      'score': 0.92,
      'percentile': 0.95,
      'weakest_group': null,
      'strategy_name': 'default_v1',
      'as_of': '2026-07-23',
      'updated_at': '2026-07-24T06:00:00+09:00',
    },
    {
      'code': '035420',
      'status': 'NO_DATA',
      'buy_grade': null,
      'score': null,
      'percentile': null,
      'weakest_group': null,
      'strategy_name': 'default_v1',
      'as_of': '2026-07-23',
      'updated_at': '2026-07-24T06:00:00+09:00',
    },
  ];

  /// `GET /api/ratings/positions` — one SELL_NOW (NAVER, REAL account) with
  /// a STOP_LOSS reason, matching `_portfolioUnified`'s 035420/REAL holding
  /// so the portfolio + detail screens both render a live sell chip.
  static final List<Map<String, dynamic>> _positionRatings = [
    {
      'broker': 'KIS',
      'account_key': 'REAL',
      'code': '035420',
      'sell_grade': 'SELL_NOW',
      'reason': {'rule': 'STOP_LOSS', 'pl_rate': -12.3, 'threshold': -10.0},
      'pl_rate': -12.3,
      'lane': 'EOD',
      'updated_at': '2026-07-24T06:00:00+09:00',
    },
  ];

  static final Map<String, dynamic> _ratingStatus = {
    'eod': {
      'finished_at': '2026-07-24T06:00:00+09:00',
      'as_of': '2026-07-23',
      'stored_count': 120,
    },
    'intraday': {'finished_at': '2026-07-24T09:31:00+09:00'},
    'scheduler_running': true,
    'strategy_name': 'default_v1',
  };

  /// `POST /api/ratings/compute?code=...` — echoes the requested [code] back
  /// with a BUY grade, so the detail screen's "등급 계산" button has a
  /// visible result to render under `USE_MOCK=true`.
  static Map<String, dynamic> _ratingCompute(String code) => {
        'code': code,
        'status': 'OK',
        'buy_grade': 'BUY',
        'score': 0.71,
        'percentile': 0.8,
        'weakest_group': null,
        'strategy_name': 'default_v1',
        'as_of': '2026-07-23',
        'updated_at': '2026-07-24T06:00:00+09:00',
      };

  static final List<Map<String, dynamic>> _alerts = [
    {
      'id': 1,
      'stock_code': '005930',
      'stock_name': '삼성전자',
      'condition': 'PRICE_ABOVE',
      'threshold': 80000.0,
      'status': 'pending',
      'created_at': '2026-05-26T10:00:00+09:00',
      'triggered_at': null,
      'post_mortem': null,
    },
    {
      'id': 2,
      'stock_code': '035420',
      'stock_name': 'NAVER',
      'condition': 'PCT_CHANGE',
      'threshold': -5.0,
      'status': 'pending',
      'created_at': '2026-05-25T15:30:00+09:00',
      'triggered_at': null,
      'post_mortem': null,
    },
    {
      'id': 3,
      'stock_code': '035720',
      'stock_name': '카카오',
      'condition': 'PRICE_ABOVE',
      'threshold': 48000.0,
      'status': 'triggered',
      'created_at': '2026-05-26T09:30:00+09:00',
      'triggered_at': '2026-05-27T14:32:00+09:00',
      'post_mortem': null,
    },
  ];
}
