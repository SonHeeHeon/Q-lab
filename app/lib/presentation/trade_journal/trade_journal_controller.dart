/// File: app/lib/presentation/trade_journal/trade_journal_controller.dart
///
/// Riverpod state for the Trade Journal screen.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/trade_journal_api.dart';
import '../../domain/entities/account.dart';

final missingTradesProvider = FutureProvider<List<TradeLite>>((ref) {
  return ref.read(tradeJournalApiProvider).listMissing();
});

final journalListProvider = FutureProvider<List<TradeJournal>>((ref) {
  return ref.read(tradeJournalApiProvider).list();
});

/// Client-side account filter (전체/모의/실전/ISA) for both journal tabs.
/// null = 전체 (no filtering). Mirrors portfolio's `brokerFilterProvider`.
///
/// The journal only ever contains KIS-executed trades — Toss trades are
/// not recorded in the trades table (Toss is live-balance-only) — so this
/// filter's universe is exactly KisAccount.values (PAPER/REAL/ISA), never
/// a Toss option.
final journalAccountFilterProvider = StateProvider<KisAccount?>((ref) => null);

/// True when [accountType] (wire value, e.g. "PAPER"/"REAL"/"ISA") should be
/// shown under [filter]. A null filter always matches (전체). Case-insensitive
/// so backend casing drift can't silently hide rows.
bool matchesAccountFilter(String accountType, KisAccount? filter) =>
    filter == null || accountType.toUpperCase() == filter.wire.toUpperCase();
