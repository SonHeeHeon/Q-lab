from __future__ import annotations

import pytest

from backend.app.core.config import settings
from backend.app.services.llm.client import (
    LLMBudgetExceededError,
    OpenAIClient,
    tokens_used_today,
)


def test_llm_budget_reservation_blocks_before_api_call(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "llm_log.jsonl"
    client = OpenAIClient(api_key="sk-test", log_path=log_path)
    monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_BUDGET", 10)

    with pytest.raises(LLMBudgetExceededError):
        client._reserve_budget(prompt="x" * 200, max_tokens=100)

    assert "budget_blocked" in log_path.read_text(encoding="utf-8")
    assert tokens_used_today(log_path) == 0


def test_llm_budget_reservation_is_released_on_failure(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "llm_log.jsonl"
    client = OpenAIClient(api_key="sk-test", log_path=log_path)
    monkeypatch.setattr(settings, "LLM_DAILY_TOKEN_BUDGET", 1_000)

    reserved = client._reserve_budget(prompt="hello", max_tokens=10)
    assert reserved > 0
    assert tokens_used_today(log_path) == reserved

    client._release_reservation(reserved)
    assert tokens_used_today(log_path) == 0
