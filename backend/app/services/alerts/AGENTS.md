<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/services/alerts/ — Alert Monitor

## Purpose
Evaluates price alert conditions against live quotes. When a condition is met (e.g., price crosses threshold), marks the alert as triggered and sends a Telegram notification.

## Key Files

| File | Description |
|------|-------------|
| `monitor.py` | Alert evaluation loop — fetches active alerts from DB, checks against current quotes, triggers notification |

## For AI Agents

### Alert Condition Types
Match `shared/domain/alert.py` `AlertCondition` enum: `PRICE_ABOVE`, `PRICE_BELOW`, `CHANGE_RATE_ABOVE`, `CHANGE_RATE_BELOW`.

### Trigger Safety
Once triggered, the alert is marked `status=TRIGGERED` in DB — do not re-fire on the same condition without user reset.

<!-- MANUAL: -->
