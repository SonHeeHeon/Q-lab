<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/domain/entities/ — Dart Entity Definitions

## Purpose
Pure Dart entity classes — no Flutter, no Riverpod, no HTTP. Mirror `shared/domain/` Python types. Used in presentation and data layers.

## Key Files

| File | Python Mirror | Description |
|------|--------------|-------------|
| `account.dart` | `account.py` | `KisAccount` enum (PAPER/REAL/ISA), `KisAccountType` |
| `alert.dart` | `alert.py` | `Alert`, `AlertCondition`, `AlertStatus`, `AlertAction` |
| `factor.dart` | `factor.py` | `FactorType` enum for quant factor catalog |
| `position.dart` | `position.py` | `BrokerType` enum (KIS/TOSS) |
| `principle.dart` | `principle.py` | `InvestmentPrinciple` |
| `stock.dart` | `stock.py` | `StockInfo`, `MarketCountry` |
| `trade.dart` | `trade.py` | `TradeDirection`, `OrderType` |
| `trade_journal.dart` | `trade_journal.py` | `TradeJournalEntry` |
| `watchlist.dart` | `watchlist.py` | `WatchlistCategory`, `WatchlistEntry` |

## For AI Agents

### `KisAccount` — fromWire Resolution Order (MUST NOT change)
```dart
static KisAccount fromWire(String s) {
  // PAPER first, then REAL, then ISA — order is inviolable
  if (s == 'PAPER') return KisAccount.paper;
  if (s == 'REAL')  return KisAccount.real;
  if (s == 'ISA')   return KisAccount.isa;
  return KisAccount.paper; // safe default
}
```

### `AlertCondition.fromWire` — Unknown Fallback
Returns `AlertCondition.priceAbove` as safe default for unrecognised wire values.

### Sync Rule
Enum wire values must match Python enum values exactly (case-sensitive uppercase strings). When adding a value, update both `entities/<file>.dart` and `shared/domain/<file>.py`.

<!-- MANUAL: -->
