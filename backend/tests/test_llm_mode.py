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


async def test_resolve_llm_overrides(service_sessionmaker, monkeypatch):
    import backend.app.services.llm.client as lc

    monkeypatch.setattr("shared.db.session.service_session", service_sessionmaker)
    # resolve는 지연 import라 shared.db.session 심볼을 패치
    model, key = await lc.resolve_llm_overrides()
    assert model == lc.settings.LLM_MODEL and key is None  # DB 비어있으면 env

    async with service_sessionmaker() as session:
        session.add(Setting(key="llm_model", value="gpt-5.5"))
        session.add(Setting(key="openai_api_key", value="sk-test-override"))
        await session.commit()
    model, key = await lc.resolve_llm_overrides()
    assert model == "gpt-5.5"
    assert key == "sk-test-override"


def test_commentary_status_helper():
    from backend.app.api.quant import (
        _commentary_inflight,
        _commentary_status_and_maybe_schedule,
    )

    scheduled: list[str] = []
    kwargs = dict(
        mode="on_view", selected_strategy="s", default_strategy="s",
        selected_date=date(2026, 8, 1), has_rows=True,
        schedule=scheduled.append,
    )
    _commentary_inflight.clear()
    # 존재하면 ready, 태스크 미등록
    assert _commentary_status_and_maybe_schedule(
        has_commentary=True, **kwargs) == "ready"
    assert scheduled == []
    # 부재+on_view+기본 전략 → generating, 1회만 예약(중복 가드)
    assert _commentary_status_and_maybe_schedule(
        has_commentary=False, **kwargs) == "generating"
    assert _commentary_status_and_maybe_schedule(
        has_commentary=False, **kwargs) == "generating"
    assert len(scheduled) == 1
    _commentary_inflight.clear()
    # scheduled 모드·비기본 전략·행 없음 → off
    assert _commentary_status_and_maybe_schedule(
        has_commentary=False, **{**kwargs, "mode": "scheduled"}) == "off"
    assert _commentary_status_and_maybe_schedule(
        has_commentary=False, **{**kwargs, "selected_strategy": "x"}) == "off"
    assert _commentary_status_and_maybe_schedule(
        has_commentary=False, **{**kwargs, "has_rows": False}) == "off"
    assert len(scheduled) == 1
    _commentary_inflight.clear()


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
