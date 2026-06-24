/// File: app/lib/data/api/stocks_api.dart
///
/// Models and API client for stock search + detail endpoints.
///   GET /api/stocks/search?q={query}&market=ALL
///   GET /api/stocks/KR/{code}
///   GET /api/stocks/US/{ticker}
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../parse_utils.dart';
import 'api_client.dart';

// ---------------------------------------------------------------------------
// Search result
// ---------------------------------------------------------------------------

class StockSearchResult {
  StockSearchResult({
    required this.symbol,
    this.code,
    required this.name,
    required this.marketCountry,
    required this.broker,
    this.market,
    this.sector,
    this.industry,
    required this.currency,
  });

  final String symbol;
  final String? code;
  final String name;
  final String marketCountry;
  final String broker;
  final String? market;
  final String? sector;
  final String? industry;
  final String currency;

  bool get isUs => marketCountry.toUpperCase() == 'US';

  /// Display code: KR uses numeric code, US uses ticker symbol.
  String get displayCode => isUs ? symbol : (code ?? symbol);

  factory StockSearchResult.fromJson(Map<String, dynamic> j) => StockSearchResult(
        symbol: (j['symbol'] as String?) ?? (j['code'] as String?) ?? '',
        code: j['code'] as String?,
        name: (j['name'] as String?) ?? '',
        marketCountry: ((j['market_country'] as String?)?.toUpperCase()) ?? 'KR',
        broker: ((j['broker'] as String?)?.toUpperCase()) ?? 'KIS',
        market: j['market'] as String?,
        sector: j['sector'] as String?,
        industry: j['industry'] as String?,
        currency: ((j['currency'] as String?)?.toUpperCase()) ?? 'KRW',
      );
}

// ---------------------------------------------------------------------------
// Price history point
// ---------------------------------------------------------------------------

class PricePoint {
  PricePoint({
    required this.date,
    required this.open,
    required this.high,
    required this.low,
    required this.close,
    this.volume,
  });

  final DateTime date;
  final double open;
  final double high;
  final double low;
  final double close;
  final int? volume;

  factory PricePoint.fromJson(Map<String, dynamic> j) => PricePoint(
        date: DateTime.tryParse((j['date'] as String?) ?? '') ?? DateTime.now(),
        open: safeDouble(j['open'], hint: 'price.open'),
        high: safeDouble(j['high'], hint: 'price.high'),
        low: safeDouble(j['low'], hint: 'price.low'),
        close: safeDouble(j['close'], hint: 'price.close'),
        volume: (j['volume'] as num?)?.toInt(),
      );
}

// ---------------------------------------------------------------------------
// Live / intraday quote
// ---------------------------------------------------------------------------

class StockQuote {
  StockQuote({this.price, this.change, this.changePct, this.asOf});

  final double? price;
  final double? change;
  final double? changePct;
  final DateTime? asOf;

  factory StockQuote.fromJson(Map<String, dynamic> j) => StockQuote(
        price: safeDoubleOrNull(j['price'], hint: 'quote.price'),
        change: safeDoubleOrNull(j['change'], hint: 'quote.change'),
        changePct: safeDoubleOrNull(j['change_pct'], hint: 'quote.changePct'),
        asOf: j['as_of'] == null ? null : DateTime.tryParse(j['as_of'] as String),
      );
}

// ---------------------------------------------------------------------------
// Fundamental factors
// ---------------------------------------------------------------------------

class StockFactor {
  StockFactor({this.per, this.pbr, this.roe, this.roa});

  final double? per;
  final double? pbr;
  final double? roe;
  final double? roa;

  factory StockFactor.fromJson(Map<String, dynamic> j) => StockFactor(
        per: safeDoubleOrNull(j['PER'] ?? j['per'], hint: 'factor.PER'),
        pbr: safeDoubleOrNull(j['PBR'] ?? j['pbr'], hint: 'factor.PBR'),
        roe: safeDoubleOrNull(j['ROE'] ?? j['roe'], hint: 'factor.ROE'),
        roa: safeDoubleOrNull(j['ROA'] ?? j['roa'], hint: 'factor.ROA'),
      );
}

// ---------------------------------------------------------------------------
// Holding info (from portfolio)
// ---------------------------------------------------------------------------

class StockHolding {
  StockHolding({
    required this.isHolding,
    this.quantity,
    this.avgBuyPrice,
    this.broker,
    this.accountId,
  });

  final bool isHolding;
  final int? quantity;
  final double? avgBuyPrice;
  final String? broker;
  final String? accountId;

  factory StockHolding.fromJson(Map<String, dynamic> j) => StockHolding(
        isHolding: (j['is_holding'] as bool?) ?? false,
        quantity: (j['quantity'] as num?)?.toInt(),
        avgBuyPrice: safeDoubleOrNull(j['avg_buy_price'], hint: 'holding.avgBuyPrice'),
        broker: j['broker'] as String?,
        accountId: j['account_id']?.toString(),
      );
}

// ---------------------------------------------------------------------------
// Watchlist membership
// ---------------------------------------------------------------------------

class StockWatchlistInfo {
  StockWatchlistInfo({
    required this.isWatchlisted,
    this.entryId,
    this.categoryId,
  });

  final bool isWatchlisted;
  final int? entryId;
  final int? categoryId;

  factory StockWatchlistInfo.fromJson(Map<String, dynamic> j) => StockWatchlistInfo(
        isWatchlisted: (j['is_watchlisted'] as bool?) ?? false,
        entryId: (j['entry_id'] as num?)?.toInt(),
        categoryId: (j['category_id'] as num?)?.toInt(),
      );
}

// ---------------------------------------------------------------------------
// Full stock detail
// ---------------------------------------------------------------------------

class StockDetail {
  StockDetail({
    required this.code,
    required this.symbol,
    required this.name,
    required this.marketCountry,
    required this.broker,
    this.market,
    this.sector,
    this.industry,
    required this.currency,
    this.asOf,
    this.latestPrice,
    this.currentQuote,
    this.factors,
    this.factorRanks,
    required this.priceHistory,
    this.holding,
    this.watchlistInfo,
  });

  final String code;
  final String symbol;
  final String name;
  final String marketCountry;
  final String broker;
  final String? market;
  final String? sector;
  final String? industry;
  final String currency;
  final DateTime? asOf;
  final PricePoint? latestPrice;
  final StockQuote? currentQuote;
  final StockFactor? factors;
  final Map<String, int>? factorRanks;
  final List<PricePoint> priceHistory;
  final StockHolding? holding;
  final StockWatchlistInfo? watchlistInfo;

  bool get isUs => marketCountry.toUpperCase() == 'US';

  /// Best available price: live quote → last close.
  double? get displayPrice => currentQuote?.price ?? latestPrice?.close;

  double? get changePct => currentQuote?.changePct;
  double? get changeAbs => currentQuote?.change;

  factory StockDetail.fromJson(Map<String, dynamic> j) {
    final history = (j['price_history'] as List?)
            ?.map((e) => PricePoint.fromJson(asJsonMap(e)))
            .toList() ??
        <PricePoint>[];

    Map<String, int>? ranks;
    if (j['factor_ranks'] is Map) {
      ranks = {};
      for (final e in (j['factor_ranks'] as Map).entries) {
        // Backend may include null for ranks it hasn't computed yet — skip.
        if (e.value != null) ranks[e.key.toString()] = (e.value as num).toInt();
      }
      if (ranks.isEmpty) ranks = null;
    }

    return StockDetail(
      code: (j['code'] as String?) ?? '',
      symbol: (j['symbol'] as String?) ?? (j['code'] as String?) ?? '',
      name: (j['name'] as String?) ?? '',
      marketCountry: ((j['market_country'] as String?)?.toUpperCase()) ?? 'KR',
      broker: ((j['broker'] as String?)?.toUpperCase()) ?? 'KIS',
      market: j['market'] as String?,
      sector: j['sector'] as String?,
      industry: j['industry'] as String?,
      currency: ((j['currency'] as String?)?.toUpperCase()) ?? 'KRW',
      asOf: j['as_of'] == null ? null : DateTime.tryParse(j['as_of'] as String),
      latestPrice:
          j['latest_price'] == null ? null : PricePoint.fromJson(asJsonMap(j['latest_price'])),
      currentQuote:
          j['current_quote'] == null ? null : StockQuote.fromJson(asJsonMap(j['current_quote'])),
      factors: j['factors'] == null ? null : StockFactor.fromJson(asJsonMap(j['factors'])),
      factorRanks: ranks,
      priceHistory: history,
      holding: j['holding'] == null ? null : StockHolding.fromJson(asJsonMap(j['holding'])),
      watchlistInfo:
          j['watchlist'] == null ? null : StockWatchlistInfo.fromJson(asJsonMap(j['watchlist'])),
    );
  }
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

class StocksApi {
  StocksApi(this._ref);
  final Ref _ref;

  Future<List<StockSearchResult>> search(String query, {String market = 'ALL'}) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>(
      '/api/stocks/search',
      queryParameters: {'q': query, 'market': market},
    );
    final list = (res.data as List?) ?? const [];
    return list.map((e) => StockSearchResult.fromJson(asJsonMap(e))).toList();
  }

  Future<StockDetail> detail(String market, String code) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/stocks/${market.toUpperCase()}/$code');
    return StockDetail.fromJson(asJsonMap(res.data));
  }
}

final stocksApiProvider = Provider<StocksApi>((ref) => StocksApi(ref));
