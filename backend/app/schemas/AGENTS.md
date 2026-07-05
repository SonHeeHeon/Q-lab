<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/schemas/ — Pydantic Request/Response Models

## Purpose
Pydantic v2 schemas for API request bodies and response payloads. `portfolio.py` is the primary file containing all portfolio-related schemas.

## Key Files

| File | Description |
|------|-------------|
| `portfolio.py` | `UnifiedPortfolioResponse`, `UnifiedPosition`, `AccountSummaryResponse`, `PlaceOrderRequest`, `PlaceOrderResponse`, `UnifiedAccountSummary` and sub-models |

## Key Schemas

| Schema | Flutter Mirror | Notes |
|--------|---------------|-------|
| `UnifiedPortfolioResponse` | `UnifiedPortfolio` | Top-level portfolio response; has `fx_rate`, `fx_as_of` |
| `UnifiedPosition` | `UnifiedPosition` | Per-position; has `currency`, `market_country` |
| `AccountSummaryResponse` | `UnifiedAccountSummary` | Per-account summary; has `cash_krw`, `cash_usd` |
| `PlaceOrderRequest` | `PlaceOrderRequest` | Order payload; `broker` field routes KIS vs TOSS |

## For AI Agents

### Decimal → String
All monetary fields use `Decimal` with `model_config = ConfigDict(json_encoders={Decimal: str})`. Flutter parses these with `safeDouble` / `safeDoubleOrNull`.

### Backward Compatibility
When adding new optional fields, give them a default of `None`. Existing Flutter clients that don't parse the new field will continue working.

### Flutter Schema Sync
After changing a schema here, update the corresponding Flutter model in `app/lib/data/api/`. Run `flutter test` after the update.

<!-- MANUAL: -->
