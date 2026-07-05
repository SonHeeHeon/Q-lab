<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# app/lib/domain/ — Domain Layer

## Purpose
Pure Dart — no Flutter, no HTTP, no Riverpod. Contains entity definitions and use-case interfaces. Mirrors `shared/domain/` Python types so the two stay in sync.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `entities/` | Dart entity classes — `Alert`, `Trade`, `Watchlist`, `KisAccount`, etc. |
| `usecases/` | Use-case interface definitions (thin; most logic lives in `data/` controllers) |

## For AI Agents

### Sync Rule
When `shared/domain/` Python types change, update the corresponding Dart entity in `entities/`. Key mirrors:
| Python | Dart |
|--------|------|
| `position.py` `BrokerType` | `portfolio_api.dart` `BrokerType` |
| `alert.py` `AlertCondition` | `entities/alert.dart` `AlertCondition` |
| `trade.py` `TradeDirection` | `entities/trade.dart` `TradeDirection` |

### No Dependencies Rule
Files in `domain/` must NOT import from `data/`, `presentation/`, or any Flutter package. Only `dart:core` and `package:equatable`.

<!-- MANUAL: -->
