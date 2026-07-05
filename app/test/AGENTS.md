<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/test/ — Flutter Unit Tests

## Purpose
Unit and widget tests for the `qlab` app. Currently focused on model parsing (JSON round-trips), domain contract tests (enum wire values, broker routing), and money format helpers. Widget tests are minimal.

## Key Files

| File | Description |
|------|-------------|
| `stocks_api_test.dart` | `StockSearchResult` / `StockDetail` model parsing; AAPL symbol preservation; US→TOSS / KR→KIS broker routing |
| `portfolio_currency_test.dart` | `UnifiedPosition` currency/market, `UnifiedPortfolio` fx_rate, `UnifiedAccountSummary` cash split, `money.dart` helpers |
| `order_alert_payload_test.dart` | `PlaceOrderRequest` broker-routing payload, `AlertAction` wire mapping |
| `fromwire_fallback_test.dart` | `KisAccount.fromWire` + `AlertCondition.fromWire` unknown-value fallbacks |
| `parse_utils_test.dart` | `safeDouble` / `safeDoubleOrNull` / `safeInt` edge cases |
| `builder_factor_guard_test.dart` | Quant builder factor-catalog exhaustion guard |
| `widget_test.dart` | Placeholder widget smoke test |

## For AI Agents

### Testing Requirements
```bash
cd app && flutter test          # all 38+ tests must pass
cd app && flutter analyze       # 0 new errors/warnings in changed files
```

### Adding New Tests
- Mirror the file name: `lib/data/api/foo_api.dart` → `test/foo_api_test.dart`
- Package import: `package:qlab/...` (not `package:stockcollect_app/`)
- Test model parsing with both complete and minimal JSON fixtures
- Test null/absent fields explicitly — the backend may omit optional fields

### What to Test
- `fromJson` for every new model class (happy path + missing fields)
- Wire-encoding for any new enum (`fromWire` round-trip + unknown fallback)
- `toJson` for any request payload (verify broker field, account_id presence/absence)

<!-- MANUAL: -->
