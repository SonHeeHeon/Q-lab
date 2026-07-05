<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/services/kis/ — KIS (한국투자증권) Client

## Purpose
Full KIS OpenAPI integration — OAuth token management, real-time quotes, order placement, portfolio fetch, rebalancer, and risk manager. Handles both 모의(PAPER) and 실전(REAL/ISA) environments.

## Key Files

| File | Description |
|------|-------------|
| `auth.py` | OAuth2 token acquisition/refresh, token cache with expiry |
| `rest_client.py` | HTTP REST client — quotes, orders, portfolio, account summary, cash balance |
| `ws_client.py` | WebSocket live quote client — connects to KIS real-time feed |
| `accounts.py` | Account-type resolution — PAPER/REAL/ISA env switching |
| `market_snapshot.py` | Market index snapshot (KOSPI/KOSDAQ) |
| `order_tracker.py` | Pending/filled order status polling |
| `rebalancer.py` | Automatic portfolio rebalance execution |
| `risk_manager.py` | Position limit / loss-cut enforcement |

## For AI Agents

### Account Validation Order (INVIOLABLE)
Resolve in this exact order: PAPER (모의) → REAL → ISA.  
Never change this order — it prevents accidental real-money orders during testing.

### Secret Safety
Never log `app_secret`, `access_token`, or any credential. `auth.py` must mask these in any exception messages.

### `rest_client.py` Cash Field
`dnca_tot_amt` → `cash_krw` (KRW). KIS does not provide USD cash.

<!-- MANUAL: -->
