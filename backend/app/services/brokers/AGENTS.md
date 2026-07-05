<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/services/brokers/ — Broker Abstraction Layer

## Purpose
Broker-agnostic interface and factory. Route handlers use `factory.py` to get a broker instance without knowing whether it's KIS or Toss.

## Key Files

| File | Description |
|------|-------------|
| `base.py` | `BrokerClient` abstract base class — `get_portfolio()`, `place_order()`, `get_quote()` interface |
| `factory.py` | `get_broker(broker_type: BrokerType) → BrokerClient` — returns KIS or Toss client |

## For AI Agents

### Two Broker Types
| `BrokerType` | Client | Used For |
|-------------|--------|---------|
| `KIS` | `kis/rest_client.py` | KR equities, KIS account |
| `TOSS` | `toss/rest_client.py` | US equities, Toss account |

### Adding a New Broker
1. Implement `BrokerClient` in a new `services/<broker>/rest_client.py`
2. Register in `factory.py`
3. Add enum value to `BrokerType` in `shared/domain/position.py` and `app/lib/domain/entities/position.dart`

<!-- MANUAL: -->
