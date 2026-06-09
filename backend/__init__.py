"""
Package: backend

FastAPI backend service. Single process runs:
  - REST API     (backend.app.api.*)
  - WebSocket    (backend.app.ws.quotes)
  - KIS clients  (backend.app.services.kis.*)
  - LLM adapter  (backend.app.services.llm.*)
  - Telegram     (backend.app.services.notify.telegram)
  - APScheduler  (backend.app.services.batch.*)

Entry point: backend.app.main:app  (`uvicorn backend.app.main:app`)
"""
