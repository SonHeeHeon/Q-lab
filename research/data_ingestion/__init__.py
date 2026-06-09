"""
Package: research.data_ingestion

Pull historical data into `research.db`.

Files:
  - pykrx_loader.py     → daily OHLCV + market index (pykrx)
  - fdr_loader.py       → backup/overseas (FinanceDataReader)
  - financial_loader.py → quarterly financials with `disclosed_at` (DART OpenAPI)
  - delisted_loader.py  → DELISTED stocks — survivorship-bias guard

Idempotency:
    All loaders use INSERT ... ON CONFLICT IGNORE. Re-running on the
    same date is harmless. Use `--allow-overwrite` flag (planned) to
    explicitly UPSERT when correcting data.

Connected modules:
    - shared.db.session.research_engine
    - shared.db.models.Stock, PriceDaily, Financials, MarketIndex
"""
