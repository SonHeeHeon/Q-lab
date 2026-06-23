/// File: app/lib/presentation/portfolio/portfolio_controller.dart
///
/// Per-account portfolio data + live-price WS bridge.
///
/// - [brokerFilterProvider]      : 전체/한투/토스 broker filter
/// - [selectedAccountProvider]   : which KIS account tab the user is on
/// - [accountDetailProvider]     : REST snapshot for the selected KIS account
/// - [unifiedPortfolioProvider]  : unified multi-broker REST snapshot
/// - WS subscription side-effect : subscribes stock_codes for live ticks.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/portfolio_api.dart';
import '../../data/ws/quotes_ws_client.dart';
import '../../domain/entities/account.dart';

/// Broker filter for the portfolio header chips (전체 / 한투 / 토스).
final brokerFilterProvider =
    StateProvider<BrokerFilter>((ref) => BrokerFilter.all);

/// Which KIS account the Portfolio screen is currently showing.
/// Defaults to PAPER for safety (matches activeAccountProvider default).
final selectedAccountProvider =
    StateProvider<KisAccount>((ref) => KisAccount.paper);

/// REST snapshot of the currently-selected KIS account.
/// Side effect: subscribes its holdings on the WS client so that
/// downstream `ref.watch(quotesProvider)` rebuilds get live prices.
final accountDetailProvider =
    FutureProvider.autoDispose<AccountDetail>((ref) async {
  final type = ref.watch(selectedAccountProvider);
  final api = ref.read(portfolioApiProvider);
  final detail = await api.getAccountDetail(type);

  final codes = detail.positions.map((p) => p.stockCode).toList();
  final quotes = ref.read(quotesProvider.notifier);
  quotes.subscribe(codes);
  ref.onDispose(() => quotes.unsubscribe(codes));

  return detail;
});

/// Multi-broker unified snapshot from `GET /api/portfolio?broker=ALL|KIS|TOSS`.
/// Used when brokerFilter is ALL or TOSS. Re-fetches when filter changes.
final unifiedPortfolioProvider =
    FutureProvider.autoDispose<UnifiedPortfolio>((ref) async {
  final filter = ref.watch(brokerFilterProvider);
  final api = ref.read(portfolioApiProvider);
  final portfolio = await api.getUnifiedPortfolio(filter);

  final codes = portfolio.positions.map((p) => p.stockCode).toList();
  final quotes = ref.read(quotesProvider.notifier);
  quotes.subscribe(codes);
  ref.onDispose(() => quotes.unsubscribe(codes));

  return portfolio;
});
