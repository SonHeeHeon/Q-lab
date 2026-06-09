"""
Module: shared.utils.time

Role:
    Korean market calendar helpers.

Planned functions:
    - is_trading_day(date) → bool
    - next_trading_day(date) → date
    - previous_trading_day(date) → date
    - market_open_dt(date) → datetime   (e.g. 09:00 KST)
    - market_close_dt(date) → datetime  (e.g. 15:30 KST)
    - is_market_open(now=None) → bool
    - trading_days(start, end) → list[date]

Data source:
    pykrx provides historical 휴장일 lists; cache locally to avoid
    repeated calls. Static configuration handles weekends.

Why centralize:
    Both APScheduler (backend.app.services.batch.*) and the research
    backtest engine (research.backtest.engine.run_backtest) iterate
    trading days; sharing one implementation guarantees identical
    universes across service and research.

Connected modules:
    - Used by: backend.app.services.batch.*, backend.app.api.heatmap,
               research.backtest.engine, research.backtest.walk_forward,
               research.data_ingestion.*
"""
