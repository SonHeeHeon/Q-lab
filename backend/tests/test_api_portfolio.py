"""
Module: backend.tests.test_api_portfolio

Role:
    Verify backend.app.api.portfolio endpoints:
      - GET /api/portfolio              → unified balance (3 accounts merged)
      - GET /api/portfolio/{type}       → single-account
      - POST /api/portfolio/orders      → creates Trade row; envelope OK
      - GET /api/portfolio/history      → filters by date/account/code

Uses mock_kis_rest fixture so no real network calls happen.
"""
