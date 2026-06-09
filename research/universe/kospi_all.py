"""
Module: research.universe.kospi_all

Role:
    All KOSPI-listed stocks AS OF `as_of` — survivorship-free.

API:
    def get_kospi_all(as_of: date) -> list[str]

Selection rule:
    SELECT code FROM stocks
    WHERE market = 'KOSPI'
      AND listed_at <= :as_of
      AND (delisted_at IS NULL OR delisted_at > :as_of)

Connected modules:
    - Reads:    research.db.stocks
    - Used by:  research.backtest.engine (when strategy.universe="KOSPI_ALL")
"""
