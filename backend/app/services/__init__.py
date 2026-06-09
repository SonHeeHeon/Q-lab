"""
Package: backend.app.services

External integrations and long-running workers.

Subpackages:
  - kis/      → KIS Open API (auth, REST, WebSocket, account registry)
  - llm/      → LLM adapter (OpenAI primary; Claude-ready) + caching
  - notify/   → Telegram bot
  - batch/    → APScheduler jobs (data sync, daily analysis, daily report)
"""
