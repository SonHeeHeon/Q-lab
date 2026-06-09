"""
Package: backend.app.services.llm

Large-language-model adapter.

Files:
  - client.py     → OpenAIClient + LLMClient Protocol (Claude-ready)
  - cache.py      → DB-backed response cache (llm_cache table)
  - prompts/      → Jinja2 prompt templates (see prompts/__init__.py)

Cost guards (see PROJECT_BLUEPRINT.md §12):
    - Cache TTL (default 24h)
    - Daily token budget (LLM_DAILY_TOKEN_BUDGET)
    - Batched prompts (N stocks per call, not 1 per stock)
    - Per-call token usage logged to data/cache/llm_log.jsonl
"""
