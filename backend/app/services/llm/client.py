"""LLM client adapter layer."""

from __future__ import annotations

import json
import time
import fcntl
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

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
        reserved_tokens = self._reserve_budget(prompt=prompt, max_tokens=max_tokens)
        started = time.perf_counter()
        # gpt-5·o 계열: max_tokens 미지원(max_completion_tokens 필수)이고
        # temperature 커스텀도 거부한다 — 모델군에 맞춰 파라미터 구성.
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a concise Korean equity research assistant.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": max_tokens,
        }
        if not model.startswith(("gpt-5", "o")):
            request_kwargs["temperature"] = 0.2
        try:
            response = await self.client.chat.completions.create(**request_kwargs)
        except Exception:
            self._release_reservation(reserved_tokens)
            raise
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
            extra={"reserved_tokens": -reserved_tokens},
        )
        return text.strip()

    def _reserve_budget(self, *, prompt: str, max_tokens: int) -> int:
        estimated_tokens = _estimate_token_upper_bound(prompt, max_tokens)
        budget = settings.LLM_DAILY_TOKEN_BUDGET
        with self._budget_lock():
            used = self._tokens_used_today()
            if used >= budget or used + estimated_tokens > budget:
                message = (
                    f"LLM daily token budget exceeded: {used}/"
                    f"{budget}, requested_estimate={estimated_tokens}"
                )
                self._append_log_unlocked(
                    model="budget-block",
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0,
                    event="budget_blocked",
                    extra={"used_tokens": used, "requested_estimate": estimated_tokens},
                )
                raise LLMBudgetExceededError(message)
            self._append_log_unlocked(
                model="budget-reservation",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
                event="budget_reserved",
                extra={"reserved_tokens": estimated_tokens},
            )
        return estimated_tokens

    def _release_reservation(self, reserved_tokens: int) -> None:
        with self._budget_lock():
            self._append_log_unlocked(
                model="budget-reservation",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
                event="budget_released",
                extra={"reserved_tokens": -reserved_tokens},
            )

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
                    total += int(row.get("reserved_tokens", 0))
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
        with self._budget_lock():
            self._append_log_unlocked(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                event=event,
                extra=extra,
            )

    def _append_log_unlocked(
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

    @contextmanager
    def _budget_lock(self):
        lock_path = self.log_path.with_suffix(self.log_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def tokens_used_today(log_path: Path | None = None) -> int:
    path = log_path or settings.resolve_path(settings.LLM_CACHE_DIR) / "llm_log.jsonl"
    if not path.exists():
        return 0
    today = date.today().isoformat()
    total = 0
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("created_at", "")).startswith(today):
                total += int(row.get("prompt_tokens", 0))
                total += int(row.get("completion_tokens", 0))
                total += int(row.get("reserved_tokens", 0))
    return total


def get_llm_client(*, api_key: str | None = None) -> LLMClient:
    if settings.LLM_PROVIDER != "openai":
        raise LLMConfigurationError(f"Unsupported LLM_PROVIDER: {settings.LLM_PROVIDER}")
    return OpenAIClient(api_key=api_key)


async def resolve_llm_overrides() -> tuple[str, str | None]:
    """(모델, API 키 오버라이드) — 설정 화면(DB Setting)이 env를 이긴다.

    2026-08-01 이전엔 설정 화면 저장값이 런타임에 반영되지 않던 반쪽 상태였음.
    키가 DB에 없으면 None(→ env 키 사용).
    """
    from shared.db.models import Setting
    from shared.db.session import service_session

    async with service_session() as session:
        model_row = await session.get(Setting, "llm_model")
        key_row = await session.get(Setting, "openai_api_key")
    model = (
        model_row.value.strip()
        if model_row is not None and str(model_row.value).strip()
        else settings.LLM_MODEL
    )
    api_key = (
        key_row.value.strip()
        if key_row is not None and str(key_row.value).strip()
        else None
    )
    return model, api_key


def _estimate_token_upper_bound(prompt: str, max_tokens: int) -> int:
    # Conservative approximation for budget gating before making the API call.
    prompt_estimate = max(1, len(prompt) // 3)
    return prompt_estimate + max_tokens
