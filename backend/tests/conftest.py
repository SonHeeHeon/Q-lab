"""
Module: backend.tests.conftest

Role:
    Shared pytest fixtures.

Planned fixtures:
    - event_loop                  (session-scoped asyncio loop)
    - tmp_service_db              (in-memory or tmp-file SQLite + migrations)
    - tmp_research_db             (likewise)
    - mock_kis_rest               (responds with canned balance/order data)
    - mock_kis_ws                 (yields a scripted sequence of ticks)
    - mock_llm_client             (returns fixed strings; no API calls)
    - test_client                 (FastAPI TestClient w/ overridden deps)
"""
