<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# shared/domain/ — Python Domain Value Objects

## Purpose
Pure Python domain types (dataclasses / Pydantic models) shared between `backend/` and `research/`. These mirror the Flutter `app/lib/domain/entities/` Dart files. No DB or HTTP dependencies — import freely in both packages.

## Key Files

| File | Description |
|------|-------------|
| `alert.py` | `Alert`, `AlertCondition`, `AlertStatus`, `AlertAction` enums |
| `position.py` | `Position`, `PortfolioSummary`, `PortfolioResponse`, `BrokerType` |
| `trade.py` | `Trade`, `TradeDirection`, `OrderType` |
| `watchlist.py` | `WatchlistCategory`, `WatchlistEntry` |
| `account.py` | `KisAccount`, `BrokerAccountRef` |
| `factor.py` | Factor value containers for research |
| `stock.py` | `StockInfo`, `PricePoint` |
| `strategy.py` | Strategy parameter containers |
| `principle.py` | Investment principle record |
| `trade_journal.py` | Trade journal entry |

## For AI Agents

### Sync with Flutter
When adding a field to a domain type here, update the corresponding Flutter entity:
- `position.py` ↔ `app/lib/data/api/portfolio_api.dart` (`UnifiedPosition`, `UnifiedPortfolio`, etc.)
- `alert.py` ↔ `app/lib/domain/entities/alert.dart`
- `trade.py` ↔ `app/lib/domain/entities/trade.dart`

### BrokerType Enum
`BrokerType.KIS` and `BrokerType.TOSS` are defined here and used throughout the backend. Wire values are `"KIS"` and `"TOSS"` (uppercase strings).

<!-- MANUAL: -->
