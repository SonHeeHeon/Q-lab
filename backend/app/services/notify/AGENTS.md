<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/services/notify/ — Notification Dispatch

## Purpose
Sends notifications to the user via Telegram. Used by the alert monitor (price trigger), daily report batch job, and order confirmation.

## Key Files

| File | Description |
|------|-------------|
| `telegram.py` | Telegram Bot API wrapper — `send_message(chat_id, text)`, rate limiting |

## For AI Agents

### Secret Safety
Telegram bot token must never be logged. Load from `Settings.telegram_bot_token`.

### Rate Limiting
Telegram Bot API has a 30 msg/sec limit per bot. `telegram.py` enforces a per-chat rate limit to prevent flooding. Do not call `send_message` in tight loops.

<!-- MANUAL: -->
