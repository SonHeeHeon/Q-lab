<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-07-06 | Updated: 2026-07-06 -->

# backend/app/services/llm/ — LLM Integration

## Purpose
OpenAI GPT integration for trade journal analysis and investment principle extraction. Includes token budget enforcement, response caching, and structured prompts.

## Key Files

| File | Description |
|------|-------------|
| `client.py` | OpenAI client wrapper — budget cap, retry logic, model selection |
| `cache.py` | LLM response cache (SQLite-backed) — avoids duplicate API calls for same input |
| `journal_analyzer.py` | Trade journal → principle extraction prompt chain |
| `prompts/` | Prompt template files |

## For AI Agents

### Cost Controls (Hard Limits)
- Max tokens per call defined in `client.py` — never bypass
- LLM calls must be user-triggered (not automatic on data load)
- Cache hit → return cached response, no API call

### Secret Safety
The OpenAI API key must never appear in logs. Load from `core/config.py` `Settings.openai_api_key`.

<!-- MANUAL: -->
