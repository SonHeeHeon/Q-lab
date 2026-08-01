"""LLM 실행 정책(llm_commentary_mode): 크론 스킵 + 조회 트리거."""
from __future__ import annotations

from datetime import date

import backend.app.services.batch.daily_report as dr
from shared.db.models import Setting


async def test_mode_defaults_to_on_view(service_sessionmaker, monkeypatch):
    monkeypatch.setattr(dr, "service_session", service_sessionmaker)
    assert await dr.llm_commentary_mode() == "on_view"


async def test_mode_scheduled_when_set(service_sessionmaker, monkeypatch):
    monkeypatch.setattr(dr, "service_session", service_sessionmaker)
    async with service_sessionmaker() as session:
        session.add(Setting(key="llm_commentary_mode", value="scheduled"))
        await session.commit()
    assert await dr.llm_commentary_mode() == "scheduled"


async def test_cron_skips_llm_in_on_view(service_sessionmaker, monkeypatch):
    monkeypatch.setattr(dr, "service_session", service_sessionmaker)
    monkeypatch.setattr(dr, "latest_research_price_date", lambda: date(2026, 8, 1))
    calls = {"n": 0}

    async def spy(*a, **k):
        calls["n"] += 1
        return "AI text"

    monkeypatch.setattr(dr, "complete_cached", spy)
    result = await dr.run_daily_report(send_telegram=False)
    assert calls["n"] == 0  # on_view(기본): 크론 경로에서 LLM 호출 없음
    assert "조회 시 생성" in result.commentary
    assert result.llm_fallback_used is False


async def test_cron_calls_llm_in_scheduled(service_sessionmaker, monkeypatch):
    monkeypatch.setattr(dr, "service_session", service_sessionmaker)
    monkeypatch.setattr(dr, "latest_research_price_date", lambda: date(2026, 8, 1))
    async with service_sessionmaker() as session:
        session.add(Setting(key="llm_commentary_mode", value="scheduled"))
        await session.commit()
    calls = {"n": 0}

    async def spy(*a, **k):
        calls["n"] += 1
        return "AI text"

    monkeypatch.setattr(dr, "complete_cached", spy)
    result = await dr.run_daily_report(send_telegram=False)
    assert calls["n"] == 1
    assert result.commentary == "AI text"
