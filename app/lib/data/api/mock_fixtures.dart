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
