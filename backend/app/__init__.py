"""
Package: backend.app

The FastAPI application package. Submodules:

  - main          → FastAPI() instance + lifespan (start WS clients, scheduler)
  - api/          → REST routers (one file per resource, mounted in main)
  - ws/           → WebSocket endpoints (Flutter ↔ backend)
  - services/     → External integrations (KIS, LLM, Telegram, batch)
  - core/         → Config, security stubs, dependency injection helpers
  - schemas/      → API request/response Pydantic models (decoupled from domain)
"""
