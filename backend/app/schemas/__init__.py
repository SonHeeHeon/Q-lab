"""
Package: backend.app.schemas

API request/response Pydantic models. **Decoupled from domain models**
on purpose: API shape may diverge from internal domain (e.g. omit
secrets, flatten relationships, paginate).

When to add a schema here vs reuse domain:
    - Reuse `shared.domain.*` directly for simple read endpoints.
    - Add a schema here when the request/response shape genuinely
      differs (e.g. PlaceOrderRequest, BacktestRunResponse with
      pagination wrappers).

Empty for now; populate as endpoints are implemented.
"""
