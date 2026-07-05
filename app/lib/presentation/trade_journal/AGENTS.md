<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/presentation/trade_journal/ — Trade Journal

## Purpose
Trade journaling screen. Users log trades with notes/rationale, then trigger an LLM analysis to extract investment principles. Post-order dialog auto-opens after a successful order to capture rationale while fresh.

## Key Files

| File | Description |
|------|-------------|
| `trade_journal_screen.dart` | `TradeJournalScreen` — list of journal entries, analysis trigger button |
| `trade_journal_controller.dart` | `tradeJournalProvider` (`FutureProvider<List<TradeJournalEntry>>`), LLM analysis action |
| `post_order_journal_dialog.dart` | `PostOrderJournalDialog` — auto-shown after order confirmation, captures trade rationale |

## For AI Agents

### LLM Cost Control
LLM analysis is user-triggered (tap button), not automatic. Never trigger on every page load — it calls OpenAI and incurs cost.

### Post-Order Dialog
`PostOrderJournalDialog` is shown from `order_sheet.dart` after a successful order response. It pre-fills ticker, direction, quantity, and price from the order payload.

<!-- MANUAL: -->
