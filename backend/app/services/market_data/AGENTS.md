<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/services/market_data/ — Market Data Aggregation

## Purpose
Aggregates real-time and snapshot market data from broker APIs. Provides quotes, heatmap sector data, stock names, and USD/KRW exchange rate used by API route handlers.

## Key Files

| File | Description |
|------|-------------|
| `quotes.py` | Current quote fetch — routes to KIS or Toss based on `broker` param |
| `fx.py` | USD/KRW exchange rate — wraps Toss `getExchangeRate`, ~60s cache |
| `names.py` | Stock name/sector lookup cache (KRX data) |

## For AI Agents

### FX Rate (`fx.py`)
Called by `GET /api/fx/rate` and embedded in `GET /api/portfolio` response as `fx_rate`/`fx_as_of`.  
Cache TTL ≈ 60 seconds (Toss updates every 1 minute).  
On Toss API failure: return `None` — Flutter shows "환율 불러오는 중" gracefully.

<!-- MANUAL: -->
