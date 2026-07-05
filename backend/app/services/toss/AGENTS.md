<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/services/toss/ — Toss Securities Client

## Purpose
Toss Securities OpenAPI integration — OAuth, quotes, orders, portfolio positions, account summary (KRW/USD cash), and USD/KRW exchange rate.

## Key Files

| File | Description |
|------|-------------|
| `rest_client.py` | HTTP REST client — auth, quotes, orders, portfolio, `_parse_summary`, `_cash_money_dict`, fx rate |
| `ws_client.py` | WebSocket live quote client for US equity ticks |

## For AI Agents

### Known Bug — `_cash_money_dict` (Pending Codex Fix)
`_cash_money_dict()` at line ~523 searches for these keys: `"cashAmount"`, `"cash"`, `"deposit"`, `"availableCash"`, `"withdrawableAmount"`, `"amount"`.  
Toss API likely uses `"depositAmount"` → not found → returns `{}` → `cash_krw=None` → Flutter hides the row.  
**Codex R2 fix**: add `"depositAmount"` to the search key list.

### Cash Fields
`_parse_summary` must populate `cash_krw` (from `amount.krw` or `depositAmount`) and `cash_usd` (from `amount.usd`) in `AccountSummaryResponse`.

### US Position Prices
US position `avg_buy_price`, `current_price` are native USD. Flutter displays them with KRW conversion via `fxRate`.

### Exchange Rate
`GET /api/v1/exchange-rate` (getExchangeRate) → `fx.py` in `market_data/` wraps this for the `GET /api/fx/rate` endpoint.

<!-- MANUAL: -->
