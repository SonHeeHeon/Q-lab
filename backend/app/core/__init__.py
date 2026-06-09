"""
Package: backend.app.core

Backend cross-cutting concerns:
  - config.py    → Settings (extends shared.utils.config) for backend-only fields
  - security.py  → Placeholder; single-user app, no auth in V1
  - deps.py      → FastAPI Depends helpers (DB sessions, KIS client)
"""
