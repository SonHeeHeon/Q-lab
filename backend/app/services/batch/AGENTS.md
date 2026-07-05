<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/services/batch/ — Scheduled Batch Jobs

## Purpose
APScheduler-based batch jobs that run on a schedule. Handles daily data sync, broker order sync, daily portfolio report generation, and analysis triggers.

## Key Files

| File | Description |
|------|-------------|
| `scheduler.py` | APScheduler setup — registers all jobs with cron triggers, started in `main.py` lifespan |
| `data_sync.py` | Daily price/factor data sync from KIS → research DB |
| `broker_order_sync.py` | Polls KIS order status for pending orders, updates DB |
| `daily_analysis.py` | Triggers LLM analysis on new journal entries (if budget allows) |
| `daily_report.py` | Generates daily portfolio snapshot + sends Telegram report |

## For AI Agents

### Job Scheduling
All jobs registered in `scheduler.py`. Add new jobs here — do not start schedulers elsewhere.

### KST Timezone
All cron schedules use KST (UTC+9). Use `timezone='Asia/Seoul'` in APScheduler job definitions.

### No Live Orders in Batch
Batch jobs must not place market orders. They may trigger rebalance via the rebalancer service if explicitly configured by the user.

<!-- MANUAL: -->
