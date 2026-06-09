/// File: app/lib/presentation/portfolio/portfolio_controller.dart
///
/// Per-account portfolio data + live-price WS bridge.
///
/// - [selectedAccountProvider]   : which account tab the user is on
/// - [accountDetailProvider]     : REST snapshot for the selected account
/// - WS subscription side-effect : whenever a new snapshot arrives, the
///   controller subscribes its stock_codes on [quotesProvider]. Per-row
///   widgets watch [quotesProvider.select((m) => m[code])] for blink-on-tick.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/portfolio_api.dart';
import '../../data/ws/quotes_ws_client.dart';
import '../../domain/entities/account.dart';

/// Which account the Portfolio screen is currently showing.
/// Defaults to PAPER for safety (matches activeAccountProvider default).
final selectedAccountProvider = StateProvider<KisAccount>((ref) => KisAccount.paper);

/// REST snapshot of the currently-selected account.
/// Side effect: subscribes its holdings on the WS client so that
/// downstream `ref.watch(quotesProvider)` rebuilds get live prices.
final accountDetailProvider = FutureProvider.autoDispose<AccountDetail>((ref) async {
  final type = ref.watch(selectedAccountProvider);
  final api = ref.read(portfolioApiProvider);
  final detail = await api.getAccountDetail(type);

  final codes = detail.positions.map((p) => p.stockCode).toList();
  final quotes = ref.read(quotesProvider.notifier);
  quotes.subscribe(codes);
  ref.onDispose(() => quotes.unsubscribe(codes));

  return detail;
});
