"""
Package: backend.tests

pytest-based tests for the FastAPI backend. Use `pytest-asyncio`.

Suggested coverage:
  - conftest.py            → shared fixtures (in-memory SQLite, mock KIS)
  - test_kis_auth.py       → token cache hit/miss, lock concurrency
  - test_api_portfolio.py  → unified balance, place_order side effects
  - test_ws_quotes.py      → alert evaluation on synthetic ticks
  - test_backtest_api.py   → sync vs async dispatch
"""
