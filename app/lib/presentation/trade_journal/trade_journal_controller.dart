/// File: app/lib/presentation/trade_journal/trade_journal_controller.dart
///
/// Riverpod state for the Trade Journal screen.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/api/trade_journal_api.dart';

final missingTradesProvider = FutureProvider<List<TradeLite>>((ref) {
  return ref.read(tradeJournalApiProvider).listMissing();
});

final journalListProvider = FutureProvider<List<TradeJournal>>((ref) {
  return ref.read(tradeJournalApiProvider).list();
});
