"""
Module: research.data_ingestion.fdr_loader

Role:
    `FinanceDataReader` adapter — used as backup for pykrx gaps and
    as the future hook for overseas (US) equities expansion.

V1 usage:
    - Cross-check pykrx values when discrepancies arise.
    - Pull market-cap data not directly served by pykrx.

V2+ usage:
    - Pull US market data (S&P 500, NASDAQ) when project scope expands.

Connected modules:
    - Writes:  research.db.prices_daily (for non-KRX tickers, when added)
    - Called by: research.scripts.download_universe (--source fdr flag)
"""
