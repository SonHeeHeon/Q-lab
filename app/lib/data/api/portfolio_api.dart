/// File: app/lib/data/api/portfolio_api.dart
///
/// Dio wrapper for `/api/portfolio*` (PROJECT_BLUEPRINT.md §8.1).
///
/// Backend schema reference: `backend/app/schemas/portfolio.py`
///   PortfolioResponse { account_type, positions[], summary{...}, raw_output2 }
///   Summary fields use Decimal → emitted as JSON strings.
library;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/entities/account.dart';
import '../../domain/entities/position.dart';
import '../parse_utils.dart';
import 'api_client.dart';

enum BrokerType {
  KIS('KIS', '한국투자증권', '한투'),
  TOSS('TOSS', '토스증권', '토스');

  const BrokerType(this.wire, this.label, this.shortLabel);
  final String wire;
  final String label;
  final String shortLabel;

  static BrokerType fromWire(String? s) => BrokerType.values.firstWhere(
        (e) => e.wire == (s ?? '').toUpperCase(),
        orElse: () => BrokerType.KIS,
      );
}

enum BrokerFilter { all, kis, toss }

class UnifiedAccountSummary {
  UnifiedAccountSummary({
    required this.broker,
    this.accountType,
    this.accountId,
    this.currency,
    required this.totalValue,
    required this.cashBalance,
    required this.totalPl,
    required this.totalPlPct,
  });

  final BrokerType broker;
  final KisAccount? accountType;
  final String? accountId;
  final String? currency;
  final double totalValue;
  final double cashBalance;
  final double totalPl;
  final double totalPlPct;

  factory UnifiedAccountSummary.fromJson(Map<String, dynamic> j) =>
      UnifiedAccountSummary(
        broker: BrokerType.fromWire(j['broker'] as String?),
        accountType: j['account_type'] != null
            ? KisAccount.fromWire(j['account_type'] as String)
            : null,
        accountId: j['account_id'] as String?,
        currency: j['currency'] as String?,
        totalValue: _d(j['total_value']),
        cashBalance: _d(j['cash_balance']),
        totalPl: _d(j['total_pl']),
        totalPlPct: _d(j['total_pl_pct']),
      );
}

class UnifiedPosition {
  UnifiedPosition({
    required this.broker,
    this.accountType,
    this.accountId,
    required this.stockCode,
    required this.stockName,
    required this.quantity,
    required this.avgBuyPrice,
    this.currentPrice,
    this.unrealizedPl,
    this.unrealizedPlPct,
  });

  final BrokerType broker;
  final KisAccount? accountType;
  final String? accountId;
  final String stockCode;
  final String stockName;
  final int quantity;
  final double avgBuyPrice;
  double? currentPrice;
  final double? unrealizedPl;
  final double? unrealizedPlPct;

  double get marketValue => (currentPrice ?? avgBuyPrice) * quantity;
  double get costBasis => avgBuyPrice * quantity;
  double get plValue => unrealizedPl ?? (marketValue - costBasis);
  double get plPct =>
      unrealizedPlPct ?? (costBasis == 0 ? 0 : (plValue / costBasis) * 100);

  factory UnifiedPosition.fromJson(Map<String, dynamic> j) => UnifiedPosition(
        broker: BrokerType.fromWire(j['broker'] as String?),
        accountType: j['account_type'] != null
            ? KisAccount.fromWire(j['account_type'] as String)
            : null,
        accountId: j['account_id'] as String?,
        stockCode: (j['stock_code'] ?? '') as String,
        stockName: (j['stock_name'] ?? j['name'] ?? '') as String,
        quantity: safeInt(j['quantity'], hint: 'unified.qty'),
        avgBuyPrice: _d(j['avg_buy_price']),
        currentPrice: safeDoubleOrNull(j['current_price'], hint: 'unified.cur'),
        unrealizedPl: safeDoubleOrNull(j['unrealized_pl'], hint: 'unified.pl'),
        unrealizedPlPct:
            safeDoubleOrNull(j['unrealized_pl_rate'], hint: 'unified.plpct'),
      );
}

class UnifiedPortfolio {
  UnifiedPortfolio({
    required this.asOf,
    required this.totalValue,
    required this.totalPl,
    required this.totalPlPct,
    required this.accounts,
    required this.positions,
    this.errors = const [],
  });

  final DateTime asOf;
  final double totalValue;
  final double totalPl;
  final double totalPlPct;
  final List<UnifiedAccountSummary> accounts;
  final List<UnifiedPosition> positions;
  final List<Map<String, dynamic>> errors;

  factory UnifiedPortfolio.fromJson(Map<String, dynamic> j) => UnifiedPortfolio(
        asOf: DateTime.tryParse(j['as_of'] as String? ?? '') ?? DateTime.now(),
        totalValue: _d(j['total_value']),
        totalPl: _d(j['total_pl']),
        totalPlPct: _d(j['total_pl_pct']),
        accounts: ((j['accounts'] as List?) ?? const [])
            .map((e) => UnifiedAccountSummary.fromJson(asJsonMap(e)))
            .toList(),
        positions: ((j['positions'] as List?) ?? const [])
            .map((e) => UnifiedPosition.fromJson(asJsonMap(e)))
            .toList(),
        errors: ((j['errors'] as List?) ?? const [])
            .map((e) => asJsonMap(e))
            .toList(),
      );
}

class AccountDetail {
  AccountDetail({
    required this.accountType,
    required this.totalValue,
    required this.cashBalance,
    required this.totalPl,
    required this.totalPlPct,
    required this.positions,
  });

  final KisAccount accountType;
  final double totalValue;
  final double cashBalance;
  final double totalPl;
  final double totalPlPct;
  final List<Position> positions;

  factory AccountDetail.fromJson(Map<String, dynamic> j) {
    final accountType = KisAccount.fromWire(j['account_type'] as String);
    final summary = j['summary'] is Map ? asJsonMap(j['summary']) : <String, dynamic>{};
    return AccountDetail(
      accountType: accountType,
      totalValue: _d(summary['total_evaluation_amount']),
      cashBalance: _d(summary['cash_amount']),
      totalPl: _d(summary['unrealized_pl']),
      totalPlPct: _d(summary['unrealized_pl_rate']),
      positions: ((j['positions'] as List?) ?? const [])
          .map((e) => Position.fromJson(asJsonMap(e), accountType))
          .toList(),
    );
  }
}

/// Client-side aggregate across the 3 KIS accounts. Built by
/// PortfolioApi.getUnifiedBalance() until the backend ships
/// `GET /api/portfolio` natively (Blueprint §8.1).
class UnifiedBalance {
  UnifiedBalance({
    required this.asOf,
    required this.totalValue,
    required this.totalPl,
    required this.totalPlPct,
    required this.accounts,
    required this.positions,
  });

  final DateTime asOf;
  final double totalValue;
  final double totalPl;
  final double totalPlPct;
  final List<AccountSummary> accounts;
  final List<Position> positions;

  factory UnifiedBalance.fromAccounts(List<AccountDetail> details) {
    final accounts = [
      for (final d in details)
        AccountSummary(
          accountType: d.accountType,
          totalValue: d.totalValue,
          cashBalance: d.cashBalance,
          totalPl: d.totalPl,
          totalPlPct: d.totalPlPct,
        ),
    ];
    final positions = [for (final d in details) ...d.positions];
    final totalValue = details.fold<double>(0, (s, d) => s + d.totalValue);
    final totalPl = details.fold<double>(0, (s, d) => s + d.totalPl);
    final costBasis = positions.fold<double>(0, (s, p) => s + p.costBasis);
    final totalPlPct = costBasis == 0 ? 0.0 : (totalPl / costBasis) * 100;

    return UnifiedBalance(
      asOf: DateTime.now(),
      totalValue: totalValue,
      totalPl: totalPl,
      totalPlPct: totalPlPct,
      accounts: accounts,
      positions: positions,
    );
  }
}

enum OrderDirection { buy, sell }

class PlaceOrderRequest {
  PlaceOrderRequest({
    required this.accountType,
    required this.stockCode,
    required this.direction,
    required this.quantity,
    this.price,
    this.broker = BrokerType.KIS,
    this.accountId,
  }) : orderType = price == null ? 'MARKET' : 'LIMIT';

  final KisAccount accountType;
  final String stockCode;
  final OrderDirection direction;
  final int quantity;
  final BrokerType broker;

  /// Toss account sequence (`account_seq`). Sent as `account_id` so the
  /// backend can route a Toss order to the right brokerage account.
  /// Null for KIS orders (account is keyed by `account_type`).
  final String? accountId;

  /// null = 시장가(MARKET); 값 지정 시 지정가(LIMIT)
  final double? price;
  final String orderType;

  Map<String, dynamic> toJson() => {
        'broker': broker.wire,
        'account_type': accountType.wire,
        'stock_code': stockCode,
        'direction': direction.name.toUpperCase(),
        'quantity': quantity,
        'order_type': orderType,
        if (price != null) 'price': price,
        if (accountId != null) 'account_id': accountId,
      };
}

class TradeReceipt {
  TradeReceipt({required this.tradeId, required this.payload});

  /// Local trade row id (nullable when backend persistence failed but
  /// KIS accepted the order).
  final int? tradeId;
  final Map<String, dynamic> payload;

  factory TradeReceipt.fromJson(Map<String, dynamic> j) {
    final tp = j['trade_persistence'];
    final tradeId = tp is Map ? (tp['trade_id'] as int?) : null;
    return TradeReceipt(tradeId: tradeId, payload: j);
  }
}

/// One account's outcome from a broker-sync request.
class BrokerSyncAccountResult {
  BrokerSyncAccountResult({
    required this.accountType,
    required this.seen,
    required this.imported,
    required this.updated,
    required this.skipped,
    required this.tradeIds,
    required this.notes,
    this.error,
    this.startDate,
    this.endDate,
  });

  final KisAccount accountType;
  final int seen;
  final int imported;
  final int updated;
  final int skipped;
  final List<int> tradeIds;
  final List<String> notes;
  final String? error;
  final DateTime? startDate;
  final DateTime? endDate;

  factory BrokerSyncAccountResult.fromJson(Map<String, dynamic> j) =>
      BrokerSyncAccountResult(
        accountType: KisAccount.fromWire(j['account_type'] as String),
        seen: (j['seen'] as num?)?.toInt() ?? 0,
        imported: (j['imported'] as num?)?.toInt() ?? 0,
        updated: (j['updated'] as num?)?.toInt() ?? 0,
        skipped: (j['skipped'] as num?)?.toInt() ?? 0,
        tradeIds: ((j['trade_ids'] as List?) ?? const [])
            .map((e) => (e as num).toInt())
            .toList(),
        notes: ((j['notes'] as List?) ?? const []).map((e) => e.toString()).toList(),
        error: j['error'] as String?,
        startDate: j['start_date'] == null
            ? null
            : DateTime.tryParse(j['start_date'] as String),
        endDate: j['end_date'] == null
            ? null
            : DateTime.tryParse(j['end_date'] as String),
      );
}

class BrokerSyncOutcome {
  BrokerSyncOutcome({
    required this.startedAt,
    required this.finishedAt,
    required this.results,
  });

  final DateTime startedAt;
  final DateTime finishedAt;
  final List<BrokerSyncAccountResult> results;

  Duration get elapsed => finishedAt.difference(startedAt);
  int get totalImported => results.fold(0, (s, r) => s + r.imported);
  int get totalUpdated => results.fold(0, (s, r) => s + r.updated);
  int get totalSeen => results.fold(0, (s, r) => s + r.seen);
  bool get hasErrors => results.any((r) => r.error != null);

  factory BrokerSyncOutcome.fromJson(Map<String, dynamic> j) => BrokerSyncOutcome(
        startedAt: DateTime.parse(j['started_at'] as String),
        finishedAt: DateTime.parse(j['finished_at'] as String),
        results: ((j['results'] as List?) ?? const [])
            .map((e) => BrokerSyncAccountResult.fromJson(asJsonMap(e)))
            .toList(),
      );
}

class PortfolioApi {
  PortfolioApi(this._ref);
  final Ref _ref;

  Future<AccountDetail> getAccountDetail(KisAccount type) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get<dynamic>('/api/portfolio/${type.wire}');
    return AccountDetail.fromJson(asJsonMap(res.data));
  }

  /// Aggregates the 3 KIS accounts client-side. Skips any account whose
  /// fetch throws (e.g. credentials missing for REAL/ISA in dev).
  Future<UnifiedBalance> getUnifiedBalance() async {
    final results = await Future.wait(
      KisAccount.values.map(
        (t) => getAccountDetail(t).then<AccountDetail?>((v) => v).catchError((_) => null),
      ),
    );
    final ok = results.whereType<AccountDetail>().toList();
    return UnifiedBalance.fromAccounts(ok);
  }

  Future<UnifiedPortfolio> getUnifiedPortfolio(BrokerFilter filter) async {
    final dio = _ref.read(dioProvider);
    final brokerParam = switch (filter) {
      BrokerFilter.all => 'ALL',
      BrokerFilter.kis => 'KIS',
      BrokerFilter.toss => 'TOSS',
    };
    final res = await dio.get<dynamic>(
      '/api/portfolio',
      queryParameters: {'broker': brokerParam},
    );
    return UnifiedPortfolio.fromJson(asJsonMap(res.data));
  }

  Future<TradeReceipt> placeOrder(PlaceOrderRequest req) async {
    final dio = _ref.read(dioProvider);
    final res = await dio.post<dynamic>('/api/portfolio/orders', data: req.toJson());
    return TradeReceipt.fromJson(asJsonMap(res.data));
  }

  /// Imports KIS app / HTS orders that are not yet present in local trades.
  /// All-null body = all accounts, last ~7 days (backend default).
  Future<BrokerSyncOutcome> syncBrokerOrders({
    KisAccount? accountType,
    DateTime? startDate,
    DateTime? endDate,
    String? stockCode,
  }) async {
    final dio = _ref.read(dioProvider);
    String? d(DateTime? dt) => dt == null
        ? null
        : '${dt.year.toString().padLeft(4, '0')}-'
            '${dt.month.toString().padLeft(2, '0')}-'
            '${dt.day.toString().padLeft(2, '0')}';
    final res = await dio.post<dynamic>(
      '/api/portfolio/orders/sync',
      data: {
        if (accountType != null) 'account_type': accountType.wire,
        if (startDate != null) 'start_date': d(startDate),
        if (endDate != null) 'end_date': d(endDate),
        if (stockCode != null) 'stock_code': stockCode,
      },
      options: Options(
        receiveTimeout: const Duration(seconds: 60),
        sendTimeout: const Duration(seconds: 60),
      ),
    );
    return BrokerSyncOutcome.fromJson(asJsonMap(res.data));
  }
}

final portfolioApiProvider = Provider<PortfolioApi>((ref) => PortfolioApi(ref));

double _d(Object? v) => safeDouble(v, hint: 'portfolio');
