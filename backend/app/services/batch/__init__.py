"""
Package: backend.app.services.batch

APScheduler jobs running inside the FastAPI process.

Files:
  - data_sync.py        → nightly: ingest today's bars into research.db
  - daily_analysis.py   → post-market: run current value-equation
                          (DEFAULT_STRATEGY_NAME) → batch_analysis_results
  - daily_report.py     → after analysis: LLM commentary + Telegram report

Cron schedules (from backend.app.core.config):
  - DATA_SYNC_CRON
  - DAILY_ANALYSIS_CRON
  - DAILY_REPORT_CRON

All jobs are idempotent (safe to re-run) and log to loguru.
"""
