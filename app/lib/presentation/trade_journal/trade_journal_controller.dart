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

/// Combined broker+account filter for the journal tabs: 전체 / (KIS) 모의 /
/// 실전 / ISA / 토스. A flat enum (rather than nesting KisAccount + a
/// separate broker flag) keeps the ChoiceChip row and the match predicate
/// simple — mirrors portfolio's `BrokerFilter` pattern.
enum JournalFilter {
  all,
  paper,
  real,
  isa,
  toss;

  String get label => switch (this) {
        JournalFilter.all => '전체',
        JournalFilter.paper => '모의',
        JournalFilter.real => '실전',
        JournalFilter.isa => 'ISA',
        JournalFilter.toss => '토스',
      };

  /// The KIS account this filter maps to, or null for 전체/토스.
  KisAccount? get kisAccount => switch (this) {
        JournalFilter.paper => KisAccount.paper,
        JournalFilter.real => KisAccount.real,
        JournalFilter.isa => KisAccount.isa,
        JournalFilter.all || JournalFilter.toss => null,
      };
}

/// Client-side account filter for both journal tabs. Defaults to 전체 (no
/// filtering). Mirrors portfolio's `brokerFilterProvider`.
final journalAccountFilterProvider =
    StateProvider<JournalFilter>((ref) => JournalFilter.all);

/// True when a trade with [broker] ("KIS" | "TOSS") and [accountType] (wire
/// value, e.g. "PAPER"/"REAL"/"ISA", null for Toss) should be shown under
/// [filter]. Case-insensitive so backend casing drift can't silently hide
/// rows.
bool matchesAccountFilter(String broker, String? accountType, JournalFilter filter) {
  switch (filter) {
    case JournalFilter.all:
      return true;
    case JournalFilter.toss:
      return broker.toUpperCase() == 'TOSS';
    case JournalFilter.paper:
    case JournalFilter.real:
    case JournalFilter.isa:
      return broker.toUpperCase() == 'KIS' &&
          accountType != null &&
          accountType.toUpperCase() == filter.kisAccount!.wire;
  }
}
