<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/presentation/quant/ — Quant Research Viewer

## Purpose
Front-end for the research pipeline. Displays backtest results, factor insights, and strategy builder output sourced from `research/reports/` via the backend quant/backtest APIs.

## Key Files / Subdirectories

| Path | Description |
|------|-------------|
| `quant_screen.dart` | `QuantScreen` — tabbed shell with Backtest Lab, Builder, Insights tabs |
| `backtest_lab/` | Backtest run viewer — equity curve chart, metrics table, walk-forward results |
| `builder/` | Strategy parameter builder UI |
| `insights_tab/` | Factor insights and scoring summary |

## For AI Agents

### Read-Only UI
The quant screen only reads pre-computed results from `research/reports/`. It does not trigger live backtest runs from the Flutter side (backtest is triggered from `research/scripts/` on the server). The `backtest_api.dart` endpoint is reserved for async status polling.

<!-- MANUAL: -->
