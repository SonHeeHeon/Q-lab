"""
Package: shared

Shared library used by BOTH `backend/` (FastAPI service) AND `research/`
(experiment lab). This is the single source of truth for:

  - Domain entities       → shared.domain
  - Database models       → shared.db
  - Cross-cutting utils   → shared.utils

Do NOT add service-specific logic here. Anything backend-only belongs in
`backend/app/services/`. Anything research-only belongs in `research/`.
"""
