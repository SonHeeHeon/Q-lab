<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/ws/ — WebSocket Quote Hub

## Purpose
Real-time quote broadcast hub. Flutter clients connect via WebSocket; the hub subscribes to KIS or Toss streaming feeds and fans out ticks to all connected Flutter sessions.

## Key Files

| File | Description |
|------|-------------|
| `quotes.py` | WebSocket endpoint + connection manager — subscribe/unsubscribe by ticker, broadcast ticks |

## For AI Agents

### Tick Message Format
```json
{ "ticker": "005930", "price": 75500.0, "change": 500.0, "change_rate": 0.67, "currency": "KRW", "timestamp": "2026-07-06T09:00:01Z" }
```
`currency` is `"KRW"` for KR tickers, `"USD"` for US tickers. Flutter uses this to decide whether to convert via `fxRate`.

### Flutter WebSocket Client
`app/lib/data/ws/quotes_ws_client.dart` → `quotesProvider` — connects on app start, emits `QuoteTick` stream consumed by portfolio and heatmap screens.

### Graceful Disconnect
The hub must handle client disconnects without crashing the broadcast loop. Use `try/except WebSocketDisconnect`.

<!-- MANUAL: -->
