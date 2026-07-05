<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/tests/ — Backend pytest Suite

## Purpose
pytest tests for the FastAPI backend. Covers portfolio API aggregation, KIS auth, LLM budget controls, market snapshots, rebalancer logic, risk manager, and Toss REST client parsing.

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | Shared fixtures — test DB session, mock broker factory |
| `test_api_portfolio.py` | Portfolio endpoint integration tests |
| `test_kis_auth.py` | KIS OAuth token refresh flow |
| `test_toss_rest_client.py` | Toss `_parse_summary` / `_parse_position` model tests |
| `test_market_snapshot.py` | Market snapshot aggregation |
| `test_rebalancer.py` | KIS rebalancer logic |
| `test_risk_manager.py` | Risk limit enforcement |
| `test_llm_budget.py` | LLM token budget / cost cap |
| `test_journal_analyzer.py` | LLM trade journal summarisation |

## For AI Agents

### Testing
```bash
pytest backend/tests/ -v
pytest backend/tests/test_toss_rest_client.py -v   # targeted
```

### Adding Tests
- Use fixtures from `conftest.py` (DB session, mock broker)
- Mock external HTTP calls with `respx` or `pytest-httpx`
- Never use real KIS/Toss credentials in tests

<!-- MANUAL: -->
