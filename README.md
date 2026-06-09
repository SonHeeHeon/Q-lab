# Q-Lab

Personal quant trading lab for Korean equities: KIS Open API, FastAPI,
SQLite, point-in-time backtesting, Optuna optimization, Telegram alerts, and a
Flutter client.

The project is local-first and single-user. Secrets stay in `.env`; runtime
databases and token caches stay under `data/`.

## Status

| Phase | Status | Output |
|---|---:|---|
| Phase 0 — Bootstrap | ✅ | Pydantic domain models, SQLAlchemy 2.x models, Alembic for `service.db` and `research.db` |
| Phase 1 — KIS Backend | ✅ | KIS auth/token cache, REST balance/orders, quote WebSocket fan-out |
| Phase 2 — Data Ingestion | ✅ | KOSPI200/KOSDAQ150/KOSDAQ prices, NASDAQ100 prices, DART/yfinance financials |
| Phase 3 — Research Engine | ✅ | Point-in-time value factors, backtest engine, reports, walk-forward, Optuna |
| Phase 4 — APIs + LLM + Batch | ✅ | Backtest/CRUD/quant/heatmap APIs, LLM cache, Telegram daily report |
| Phase 5 — Flutter Integration | 🚧 | Frontend is developed separately in `app/` |
| Phase 6 — Automation + Safety | 🚧 | Order tracking, broker-order sync, rebalancer, risk manager, macOS LaunchAgent |

`PROJECT_BLUEPRINT.md` remains the design source of truth. This README is the
operator guide for the implementation that exists today.

## Repository Layout

```text
backend/   FastAPI, KIS, LLM, Telegram, APScheduler, macOS deploy scripts
research/  Data ingestion, factors, backtest engine, reports, optimization
shared/    Domain models and SQLAlchemy models shared by backend/research
app/       Flutter client, owned by the frontend track
data/      Runtime DBs, KIS tokens, manual universe files, caches
```

Codex backend/research work must not modify `app/`.

## Setup

```bash
python -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
```

Fill `.env` with KIS, DART, OpenAI, and Telegram values as needed.

Apply migrations:

```bash
.venv/bin/python -m alembic --name service upgrade head
.venv/bin/python -m alembic --name research upgrade head
```

Run the API locally:

```bash
KIS_WS_AUTOSTART=false BATCH_SCHEDULER_AUTOSTART=false \
ORDER_TRACKER_AUTOSTART=false \
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## Data Ingestion

KOSPI200 and KOSDAQ150 universes can be refreshed from Settings API or from
CLI/manual CSV. When KRX/pykrx is unavailable, `data/manual/kospi200_codes.csv`
and `data/manual/kosdaq150_codes.csv` are safe manual fallbacks.

Full 10-year collection:

```bash
.venv/bin/python research/scripts/download_universe.py \
  --universe KOSPI200 \
  --years 10 \
  --price-concurrency 4 \
  --financial-concurrency 2 \
  --pykrx-sleep 0.2 \
  --dart-sleep 0.3
```

KOSDAQ150 collection uses the same Korean `stocks`, `prices_daily`, and
`financials` tables, with `stocks.market='KOSDAQ'`:

```bash
.venv/bin/python research/scripts/download_universe.py \
  --universe KOSDAQ150 \
  --years 10 \
  --price-concurrency 4 \
  --financial-concurrency 2 \
  --pykrx-sleep 0.2 \
  --dart-sleep 0.3
```

For the full KOSDAQ market, use `--universe KOSDAQ_ALL`. This can take much
longer than KOSDAQ150 because it includes many more tickers.

NASDAQ100 data is stored separately to preserve KRW/Korean schema compatibility:
`stocks_us`, `prices_daily_us`, and `financials_us` use USD and US tickers such
as `AAPL` and `NVDA`.

```bash
.venv/bin/python research/scripts/download_us_universe.py \
  --universe NASDAQ100 \
  --years 10 \
  --sleep 0.25
```

If prices are already loaded and only DART financials need to resume:

```bash
.venv/bin/python research/scripts/download_universe.py \
  --codes-file data/manual/kospi200_codes.csv \
  --years 10 \
  --skip-delisted \
  --skip-indices \
  --skip-prices \
  --financial-concurrency 2 \
  --dart-sleep 0.3
```

## Backtest And Optimization

Smoke backtest:

```bash
.venv/bin/python research/scripts/run_backtest.py \
  --strategy research/strategies/value_v1.yaml \
  --tag smoke
```

Optuna optimization for the value strategy:

```bash
mkdir -p logs/research
nohup .venv/bin/python -m research.optimization.optuna_runner \
  --strategy research/strategies/value_v1.yaml \
  --trials 100 \
  --objective sharpe \
  --study-name value_v1_sharpe_100 \
  > logs/research/value_v1_optuna_100.log 2>&1 &
tail -f logs/research/value_v1_optuna_100.log
```

Outputs are written under `research/reports/optimization/` and the Optuna study
DB is stored at `research/reports/optuna_studies.db`.

## Research Sandbox

JupyterLab is available for hands-on factor research and regression experiments:

```bash
backend/scripts/run_jupyter.sh
```

Open these starter notebooks:

```text
research/notebooks/01_factor_exploration.ipynb
research/notebooks/02_data_visualization.ipynb
```

The notebooks read from `data/research.db`, keep financial joins
point-in-time safe with `disclosed_at <= as_of`, and include examples for
PER/PBR/ROE scoring, simple regression sketches, and price/factor plots.

## Backend APIs

Common response envelope:

```json
{"data": "...", "error": null}
```

Important endpoints:

```text
GET  /api/portfolio
GET  /api/portfolio/{account_type}
POST /api/portfolio/orders
POST /api/portfolio/orders/sync
GET  /api/quant/undervalued
GET  /api/heatmap?market=KOSPI&group_by=sector
POST /api/backtest/run
GET  /ws/quotes
```

Manual broker-order sync for KIS app/HTS orders:

```bash
curl -s -X POST http://127.0.0.1:8000/api/portfolio/orders/sync \
  -H "Content-Type: application/json" \
  -d '{"account_type":"PAPER"}' | python -m json.tool
```

Default sync window is the last 7 days. Override it per request:

```json
{
  "account_type": "PAPER",
  "start_date": "2026-05-01",
  "end_date": "2026-06-09"
}
```

For scheduled broker sync, configure:

```bash
BATCH_SCHEDULER_AUTOSTART=true
BROKER_ORDER_SYNC_CRON="10 16 * * MON-FRI"
BROKER_ORDER_SYNC_LOOKBACK_DAYS=7
BROKER_ORDER_SYNC_ACCOUNTS=PAPER,REAL,ISA
```

The 7-day lookback is important: deployed users can change
`BROKER_ORDER_SYNC_LOOKBACK_DAYS` in `.env` and restart the backend.

## Automation And Safety

Order tracking:

- App-submitted orders are saved to `service.db.trades`.
- `ORDER_TRACKER_AUTOSTART=true` polls pending/partial orders and updates fill
  state, fill price, fees, taxes, and timestamps.

Broker-order sync:

- KIS app/HTS orders are not tracked continuously by default.
- They are imported via `POST /api/portfolio/orders/sync` or the daily scheduled
  broker sync job.

Rebalancer:

- `backend.app.services.kis.rebalancer` compares target portfolio weights with
  KIS holdings and creates market-order deltas.
- `REBALANCER_IS_MOCK=true` by default, so no live orders are sent unless
  explicitly disabled.

Risk manager:

- `backend.app.services.kis.risk_manager` watches real-time quote ticks and can
  market-sell a full position when `RISK_MANAGER_STOP_LOSS_PCT` is breached.
- It is disabled and mock-only by default:

```bash
RISK_MANAGER_AUTOSTART=false
RISK_MANAGER_IS_MOCK=true
RISK_MANAGER_ACCOUNT_TYPE=PAPER
RISK_MANAGER_STOP_LOSS_PCT=-10.0
```

Turn on live automation only after paper-trading validation.

## LLM And Telegram

Daily batch:

- `daily_analysis` selects undervalued stocks.
- `daily_report` asks the LLM for commentary and sends Telegram.
- LLM calls use `llm_cache` and `LLM_DAILY_TOKEN_BUDGET`.

Backtests, data ingestion, and Optuna optimization do not call LLM APIs.

## macOS Always-On Mode

Install LaunchAgent:

```bash
.venv/bin/python backend/scripts/deploy/install_macos_launch_agent.py
```

Check:

```bash
launchctl print gui/$(id -u)/com.stockcollect.backend
tail -f logs/backend/backend.log
```

Remove:

```bash
.venv/bin/python backend/scripts/deploy/uninstall_macos_launch_agent.py
```

During development, keep LaunchAgent removed to avoid port conflicts and
unexpected scheduled jobs.

## Tests

```bash
.venv/bin/python -m pytest
```

Coverage currently includes:

- KIS rebalancer planning and mock/live submission behavior
- Risk manager stop-loss behavior with mocked KIS and Telegram
- LLM journal analyzer prompt/JSON parsing
- Backtest engine smoke test with an isolated temporary `research.db`

## Safety Defaults

Real-money automation is opt-in.

```text
REBALANCER_IS_MOCK=true
RISK_MANAGER_AUTOSTART=false
RISK_MANAGER_IS_MOCK=true
BATCH_SCHEDULER_AUTOSTART=false
```

Keep these defaults while developing. Flip them only after reviewing logs,
paper-trading behavior, and KIS account settings.
