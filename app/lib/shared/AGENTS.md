<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/shared/ — Reusable Utilities & Widgets

## Purpose
Cross-feature shared code. `format/` has pure Dart formatting utilities (no Flutter dependency). `widgets/` has reusable Flutter widgets used across multiple feature screens.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `format/` | `money.dart` — KRW/USD formatting, `usdToKrw` conversion, `formatNative` |
| `widgets/` | Common UI components (loading states, error placeholders, badges) |

## Key Files

| File | Description |
|------|-------------|
| `format/money.dart` | `krwFmt`, `usdFmt`, `formatNative(amt, currency)`, `usdToKrw(usd, fxRate?)` |

## For AI Agents

### Use `money.dart` for All Monetary Formatting
Never format currency inline in screens. Route all formatting through `money.dart`:
```dart
import '../../shared/format/money.dart';
// KR:
krwFmt.format(price)
// US (native):
usdFmt.format(price)
// US (KRW-converted):
usdToKrw(price, portfolio.fxRate) != null
  ? krwFmt.format(usdToKrw(price, portfolio.fxRate)!)
  : '--'
```

<!-- MANUAL: -->
