"""
Module: backend.app.services.batch.data_sync

Role:
    Nightly job that incrementally ingests today's market data into
    `research.db`. Keeps the backtest universe perpetually current
    so the in-app Backtest Lab can include the latest trading day.

Schedule:
    Default: 18:00 KST on trading days (settings.DATA_SYNC_CRON).

Steps:
    1. Determine missing dates (last_loaded → today).
    2. Call research.data_ingestion.pykrx_loader.update_prices(dates).
    3. If a new quarterly disclosure window passed:
         research.data_ingestion.financial_loader.update().
    4. Refresh research.data_ingestion.delisted_loader (weekly).
    5. Re-compute factor_values for affected dates.

Idempotency:
    All inserts use `INSERT ... ON CONFLICT IGNORE`. Re-running on
    the same date is harmless.

Connected modules:
    - research.data_ingestion.*
    - research.factors.* (re-compute step)
    - shared.utils.time.trading_days
    - Triggered by: APScheduler started in backend.app.main.lifespan
"""
