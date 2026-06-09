"""LLM-assisted trade journal review against user investment principles."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.core.config import settings
from backend.app.services.llm.cache import complete_cached
from backend.app.services.llm.client import LLMError
from shared.db.models import Principle, TradeJournalEntry
from shared.db.session import service_session

logger = logging.getLogger(__name__)


async def analyze_trade_journal_entry(journal_id: int) -> None:
    """Analyze one journal entry and persist summary/tags on the same row."""

    async with service_session() as session:
        stmt = (
            select(TradeJournalEntry)
            .where(TradeJournalEntry.id == journal_id)
            .options(
                selectinload(TradeJournalEntry.trade),
                selectinload(TradeJournalEntry.applied_principles),
            )
        )
        result = await session.execute(stmt)
        entry = result.scalar_one_or_none()
        if entry is None:
            logger.info("journal analysis skipped; entry not found id=%s", journal_id)
            return
        principles = list((await session.execute(select(Principle))).scalars())
        prompt = _build_prompt(entry, principles)

    try:
        response = await complete_cached(
            prompt,
            model=settings.LLM_MODEL,
            max_tokens=700,
            ttl_hours=settings.LLM_CACHE_TTL_HOURS,
        )
        parsed = _parse_response(response)
    except LLMError as exc:
        logger.warning("journal LLM analysis unavailable id=%s: %s", journal_id, exc)
        parsed = {
            "summary": f"LLM analysis unavailable: {exc}",
            "violation_tags": [],
        }
    except Exception:
        logger.exception("journal LLM analysis failed id=%s", journal_id)
        parsed = {
            "summary": "LLM analysis failed unexpectedly. Check backend logs.",
            "violation_tags": [],
        }

    async with service_session() as session:
        entry = await session.get(TradeJournalEntry, journal_id)
        if entry is None:
            return
        entry.llm_analysis_summary = str(parsed.get("summary") or "").strip() or None
        entry.llm_violation_tags = json.dumps(
            _clean_tags(parsed.get("violation_tags")),
            ensure_ascii=False,
        )
        entry.llm_analyzed_at = datetime.now()
        entry.llm_analysis_model = settings.LLM_MODEL
        await session.commit()


def _build_prompt(entry: TradeJournalEntry, principles: list[Principle]) -> str:
    trade = entry.trade
    all_principles = "\n".join(
        f"- [{principle.category}] {principle.title}: {principle.body}"
        for principle in sorted(principles, key=lambda item: (item.category, item.id))
    )
    applied = "\n".join(
        f"- [{principle.category}] {principle.title}: {principle.body}"
        for principle in entry.applied_principles
    ) or "- 사용자가 명시적으로 연결한 원칙 없음"

    return f"""
너는 개인 투자자의 매매 복기를 돕는 엄격하지만 간결한 한국어 코치다.
아래 매매일지와 투자 원칙을 비교해서, 원칙 준수 여부와 위반 태그를 판단하라.

반드시 JSON 객체만 반환하라. 형식:
{{
  "summary": "한국어 2~4문장 요약",
  "violation_tags": ["태그1", "태그2"],
  "violated_principles": ["원칙 제목"],
  "confidence": 0.0
}}

[거래]
- 계좌: {trade.account_type if trade else "unknown"}
- 종목: {trade.stock_code if trade else "unknown"}
- 방향: {entry.direction}
- 수량: {trade.quantity if trade else "unknown"}
- 가격: {trade.price if trade else "unknown"}
- 상태: {getattr(trade, "status", "unknown") if trade else "unknown"}

[사용자가 이 일지에 연결한 원칙]
{applied}

[전체 투자 원칙]
{all_principles or "- 등록된 원칙 없음"}

[매수/매도 이유]
{entry.reason}

[사후 복기]
{entry.post_review or "아직 작성되지 않음"}
""".strip()


def _parse_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"summary": cleaned[:1200], "violation_tags": []}
    if not isinstance(payload, dict):
        return {"summary": str(payload), "violation_tags": []}
    return payload


def _clean_tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = str(item).strip()
        if tag and tag not in tags:
            tags.append(tag[:40])
    return tags[:10]
