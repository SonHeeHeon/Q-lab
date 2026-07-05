<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# research/data_ingestion/ — Market Data Loaders

## Purpose
Downloads and normalises historical price, financial statement, and universe data from public sources (FinanceDataReader, pykrx, KRX). Feeds the `backtest/` and `factors/` pipelines.

## Key Files

| File | Description |
|------|-------------|
| `fdr_loader.py` | FinanceDataReader — OHLCV prices for KR/US markets |
| `pykrx_loader.py` | pykrx — KRX listing data, sector info, per-share data |
| `financial_loader.py` | Financial statement loader — PER, PBR, ROE, ROA from KRX or FDR |
| `delisted_loader.py` | Loads delisted stock history to prevent survivorship bias |

## For AI Agents

### Survivorship Bias Prevention
Always include delisted data when building universe: pass `include_delisted=True` or call `delisted_loader.load()` before filtering.

### Data Alignment
Raw data returned as pandas DataFrame with DatetimeIndex (UTC). The `engine.py` aligns signals to T-1 — loaders must NOT forward-fill beyond last known date.

### Caching
Loaders cache downloaded data in `research/data/`. Do not delete cached parquet files mid-run.

<!-- MANUAL: -->
