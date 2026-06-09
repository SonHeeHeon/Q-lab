from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from backend.app.services.llm.journal_analyzer import (
    _build_prompt,
    _clean_tags,
    _parse_response,
)
from shared.db.models import Principle, Trade, TradeJournalEntry


def test_journal_prompt_contains_trade_reason_and_principles() -> None:
    trade = Trade(
        id=1,
        account_type="PAPER",
        stock_code="005930",
        direction="BUY",
        quantity=3,
        price=Decimal("70000"),
        executed_at=datetime.now(),
        status="FILLED",
    )
    principle = Principle(
        id=1,
        title="손절 원칙",
        body="-10% 이탈 시 감정 없이 손절한다.",
        category="risk",
    )
    entry = TradeJournalEntry(
        id=1,
        trade_id=1,
        direction="BUY",
        reason="저평가 구간에서 분할 매수",
        post_review="손절 기준을 다시 확인했다.",
        trade=trade,
        applied_principles=[principle],
    )

    prompt = _build_prompt(entry, [principle])

    assert "저평가 구간에서 분할 매수" in prompt
    assert "손절 원칙" in prompt
    assert "005930" in prompt
    assert "반드시 JSON 객체만 반환" in prompt


def test_parse_response_accepts_fenced_json_and_cleans_tags() -> None:
    response = """
```json
{"summary":"원칙을 일부 지켰다.","violation_tags":["뇌동매매","뇌동매매","  "]}
```
"""

    parsed = _parse_response(response)

    assert parsed["summary"] == "원칙을 일부 지켰다."
    assert _clean_tags(parsed["violation_tags"]) == ["뇌동매매"]
