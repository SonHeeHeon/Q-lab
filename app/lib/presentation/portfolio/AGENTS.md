<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/presentation/portfolio/ — Portfolio Screen

## Purpose
Main portfolio overview screen. Shows unified portfolio (all brokers), per-account summaries with cash (KRW/USD), and positions split into KR/US sections. Live quotes via WebSocket. Buy/Sell via `showOrderSheet`.

## Key Files

| File | Description |
|------|-------------|
| `portfolio_screen.dart` | `PortfolioScreen` — `_UnifiedContent`, `_UnifiedPositionRow`, `_AccountSummaryTile`, `_UnifiedSummaryCard` |
| `portfolio_controller.dart` | `portfolioProvider` (`FutureProvider<UnifiedPortfolio>`), refresh actions |
| `order_sheet.dart` | `showOrderSheet(context, ref, OrderSheetArgs)` — broker-routing buy/sell dialog |

## For AI Agents

### KR/US Section Split
Positions are split by `position.isUs` (= `marketCountry == 'US'`):
- Section `🇰🇷 국내` — KR positions, KRW pricing
- Section `🇺🇸 해외` — US positions, KRW primary + USD secondary via `fxRate`

### Exchange Rate Display
`portfolio.fxRate != null` → show "환율 ₩{rate}/$1 · {fxAsOf HH:mm}" chip near summary card.  
`fxRate == null` → show "환율 불러오는 중", US KRW amounts show `--`.

### Cash Display (`_AccountSummaryTile`)
```
예수금  ₩3,200,000                    // KRW only (KIS)
예수금  ₩500,000 · $1,250.00          // KRW + USD (Toss)
```
Show cash row only when `cashKrw != null || cashUsd != null`.

### `showOrderSheet` — Broker Routing
```dart
showOrderSheet(context, ref, OrderSheetArgs(
  broker: position.isUs ? BrokerType.TOSS : BrokerType.KIS,
  account: position.isUs ? KisAccount.paper : KisAccount.fromWire(activeType.name.toUpperCase()),
  accountId: position.isUs ? tossAccountId : null,
  stockCode: position.isUs ? position.symbol : position.code,
  ...
));
```

<!-- MANUAL: -->
