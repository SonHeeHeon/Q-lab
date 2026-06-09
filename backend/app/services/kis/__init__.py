"""
Package: backend.app.services.kis

Korea Investment & Securities (KIS) Open API integration.

Files:
  - accounts.py     → KISClientRegistry (one client per AccountType)
  - auth.py         → token_manager (REST access_token + WS approval_key)
  - rest_client.py  → balance, orders, scheduled-sell endpoints
  - ws_client.py    → WebSocket: subscribe H0STCNT0, parse, reconnect

Endpoint bases (selected by AccountType):
  REAL/ISA  → https://openapi.koreainvestment.com:9443
            → ws://ops.koreainvestment.com:21000
  PAPER     → https://openapivts.koreainvestment.com:29443
            → ws://ops.koreainvestment.com:31000

Reference: PROJECT_BLUEPRINT.md §10 (KIS API Integration Playbook).
"""
