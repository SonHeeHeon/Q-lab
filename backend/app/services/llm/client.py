"""LLM client adapter layer."""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from openai import AsyncOpenAI

from backend.app.core.config import settings


class LLMError(RuntimeError):
    """Base LLM pipeline error."""


class LLMConfigurationError(LLMError):
    """Raised when provider credentials are missing."""


class LLMBudgetExceededError(LLMError):
    """Raised when the daily token budget has been consumed."""


class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int = 1024,
    ) -> str: ...


class OpenAIClient:
    """OpenAI-backed implementation of the LLMClient protocol."""

    def __init__(self, *, api_key: str | None = None, log_path: Path | None = None) -> None:
        self.api_key = api_key or settings.OPENAI_API_KEY.get_secret_value()
        if not self.api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is not configured.")
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.log_path = log_path or settings.resolve_path(settings.LLM_CACHE_DIR) / "llm_log.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int = 1024,
    ) -> str:
        self._assert_budget_available(prompt=prompt, max_tokens=max_tokens)
        started = time.perf_counter()
        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a concise Korean equity research assistant.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        text = response.choices[0].message.content or ""
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        self._append_log(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )
        return text.strip()

    def _assert_budget_available(self, *, prompt: str, max_tokens: int) -> None:
        used = self._tokens_used_today()
        estimated_tokens = _estimate_token_upper_bound(prompt, max_tokens)
        budget = settings.LLM_DAILY_TOKEN_BUDGET
        if used >= budget or used + estimated_tokens > budget:
            message = (
                f"LLM daily token budget exceeded: {used}/"
                f"{budget}, requested_estimate={estimated_tokens}"
            )
            self._append_log(
                model="budget-block",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
                event="budget_blocked",
                extra={"used_tokens": used, "requested_estimate": estimated_tokens},
            )
            raise LLMBudgetExceededError(message)

    def _tokens_used_today(self) -> int:
        if not self.log_path.exists():
            return 0
        today = date.today().isoformat()
        total = 0
        with self.log_path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(row.get("created_at", "")).startswith(today):
                    total += int(row.get("prompt_tokens", 0))
                    total += int(row.get("completion_tokens", 0))
        return total

    def _append_log(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        event: str = "completion",
        extra: dict[str, object] | None = None,
    ) -> None:
        row = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "provider": "openai",
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
        }
        if extra:
            row.update(extra)
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False))
            file.write("\n")


def get_llm_client() -> LLMClient:
    if settings.LLM_PROVIDER != "openai":
        raise LLMConfigurationError(f"Unsupported LLM_PROVIDER: {settings.LLM_PROVIDER}")
    return OpenAIClient()


def _estimate_token_upper_bound(prompt: str, max_tokens: int) -> int:
    # Conservative approximation for budget gating before making the API call.
    prompt_estimate = max(1, len(prompt) // 3)
    return prompt_estimate + max_tokens
