"""
Package: backend.app.api

REST routers. One file per resource group. All routers are mounted in
`backend.app.main`.

Routers and their URL prefixes:
  - portfolio.py       → /api/portfolio
  - watchlist.py       → /api/watchlist
  - trade_journal.py   → /api/trade-journal
  - alerts.py          → /api/alerts
  - quant.py           → /api/quant
  - backtest.py        → /api/backtest    (UI-triggered backtests)
  - principles.py      → /api/principles
  - heatmap.py         → /api/heatmap
  - settings.py        → /api/settings

Response envelope (all endpoints):
    { "data": <result>, "error": null }      on success
    { "data": null, "error": { "code", "message", "details" } }   on failure
"""
