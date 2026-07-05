<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/api/ — Route Handlers

## Purpose
FastAPI route handler modules, one file per resource domain. Each file defines an `APIRouter` that is included in `main.py`. Handlers are thin: validate input, call a service, return schema.

## Key Files

| File | Description |
|------|-------------|
| `portfolio.py` | `GET /api/portfolio` — aggregates KIS + Toss positions, account summaries, cash, fx_rate |
| `quotes.py` | `GET /api/quotes/current` — current quote fetch from broker (KIS or Toss) |
| `stocks.py` | `GET /api/stocks/search`, `GET /api/stocks/{market}/{code}` — stock search and detail |
| `alerts.py` | CRUD for price alerts — list, create, update, delete, trigger check |
| `watchlist.py` | CRUD for watchlist categories and entries |
| `heatmap.py` | `GET /api/heatmap` — real-time sector heat data |
| `trade_journal.py` | Trade journal CRUD + LLM analysis trigger |
| `principles.py` | Investment principle CRUD |
| `quant.py` | Backtest result retrieval from `research/reports/` |
| `backtest.py` | Backtest trigger (async job submission) |
| `screener.py` | Stock screener endpoint |
| `fx.py` | `GET /api/fx/rate` — USD/KRW exchange rate from Toss |
| `settings.py` | App settings persistence |
| `system.py` | Health check, version |

## For AI Agents

### Response Envelope
All responses must use the shared envelope:
```python
return {"data": payload, "error": None}
# or on error:
return JSONResponse(status_code=4xx, content={"data": None, "error": {"code": "...", "message": "..."}})
```

### Never Log Secrets
Do not log `app_secret`, API keys, tokens, or account numbers at any log level.

### Thin Handlers
Route handlers must not contain business logic. Extract to `services/` and call from the handler. Handler responsibility: auth check → parse input → call service → return schema.

<!-- MANUAL: -->
