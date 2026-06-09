"""
Package: shared.domain

Pure Pydantic models (no DB binding). One file per logical entity.

Files & their entities:
  - stock.py          → Stock                            (master ticker record)
  - account.py        → KISAccount, AccountType          (3 KIS accounts)
  - position.py       → Position                         (open holdings)
  - trade.py          → Trade, TradeDirection            (executed orders)
  - alert.py          → Alert, AlertCondition            (price/condition alerts)
  - principle.py      → Principle, PrincipleCategory     (투자 철학 tiles)
  - factor.py         → FactorValue                      (computed factor values)
  - watchlist.py      → WatchlistCategory, WatchlistEntry
  - trade_journal.py  → TradeJournalEntry                (buy/sell reasons)
  - strategy.py       → StrategyDefinition, FactorWeight, FilterRule

Connections:
  - Mirrored by SQLAlchemy ORM classes in `shared.db.models`
  - Consumed by `backend.app.api.*` (REST request/response shapes)
  - Consumed by `research.backtest.engine` (strategy / factor schemas)
  - Mirrored in Flutter as `app/lib/domain/entities/*.dart`
"""
