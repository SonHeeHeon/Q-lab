"""
Package: shared.db

SQLAlchemy 2.x ORM models and engine/session management for BOTH local
SQLite databases:

  - service.db   (runtime: positions, alerts, watchlist, journal, principles)
  - research.db  (historical: prices, financials, factors, delisted records)

Files:
  - models.py        → All ORM classes (mirror shared.domain Pydantic models)
  - session.py       → engine factory + AsyncSession per DB
  - migrations/      → Alembic migrations (single folder, two targets)

Why two DBs:
    Splitting runtime data from large historical data lets you back up
    or reset one without touching the other, and lets the research
    workflow churn `research.db` aggressively without risking the
    user-authored data in `service.db`.
"""
