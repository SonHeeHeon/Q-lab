"""
Package: research.factors

Factor library. Each module computes a family of factors with a
consistent signature:

    def compute(as_of: date, codes: list[str]) -> dict[str, float]

The `as_of` parameter is REQUIRED and used inside each function to
filter source data:
    - prices: date <= as_of
    - financials: disclosed_at <= as_of   (point-in-time guard)

Files:
  - value.py     → PER, PBR, PSR, PCR, EV_EBITDA
  - quality.py   → ROE, ROA, debt_ratio
  - momentum.py  → returns over 1m, 3m, 6m, 12m
  - volume.py    → volume_spike, turnover

Output:
    Computed values are persisted to `research.db.factor_values`
    (PK: stock_code, date, factor_name) by the daily data_sync job.
"""
