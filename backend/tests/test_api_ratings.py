"""/api/ratings 라우터 테스트 (Phase T5): 조회 3종 + 온디맨드 재계산.

store.py는 shared.db.session.service_session을 모듈 스코프로 import했으므로
in-memory 테스트 DB(service_sessionmaker)로 monkeypatch 해야 실제
data/service.db를 건드리지 않는다 (test_rating_batch.py와 동일 패턴).
라우터 함수를 FastAPI 없이 직접 호출해 Depends(session)는 fixture 값을
그대로 넘긴다 (test_proposals_api.py와 동일 패턴).
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse

import backend.app.api.ratings as ratings_api
import backend.app.api.settings as settings_api
from backend.app.services.ratings import store
from backend.app.services.ratings.buy_axis import BuyRating, BuyRatingsResult
from shared.db.models import StockRating
from shared.domain.strategy import StrategyDefinition


def _strategy(**overrides) -> StrategyDefinition:
    payload = dict(
        name="ratings_api_test",
        description="ratings api tests",
        universe="KOSPI200",
        rebalance_freq="QUARTERLY",
        factors=[],
        filters=[],
        top_n=5,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    payload.update(overrides)
    return StrategyDefinition.model_validate(payload)


def _fake_compute_buy_ratings(strategy, extra_codes=(), *, as_of=None, db_path=None):
    del as_of, db_path  # 합성 결과라 참고하지 않는다.
    ratings = [
        BuyRating(
            code=code,
            status="OK",
            buy_grade="BUY",
            score=0.6,
            percentile=0.7,
            weakest_group=None,
        )
        for code in extra_codes
    ]
    return BuyRatingsResult(
        as_of="2026-07-24",
        strategy_name=strategy.name,
        universe_size=0,
        ratings=ratings,
        warnings=[],
    )


@pytest.fixture(autouse=True)
def _patch_store_db(monkeypatch, service_sessionmaker):
    monkeypatch.setattr(store, "service_session", service_sessionmaker)


# --- GET /api/ratings --------------------------------------------------------------

async def test_get_ratings_returns_seeded_rows(service_session):
    service_session.add(
        StockRating(
            code="005930",
            status="OK",
            buy_grade="BUY",
            score=0.7,
            percentile=0.8,
            weakest_group=None,
            strategy_name="qlab_alpha_v2",
            as_of=date(2026, 7, 24),
            updated_at=datetime(2026, 7, 24, 19, 0, 0),
        )
    )
    await service_session.commit()

    envelope = await ratings_api.get_ratings(codes="005930,000660")

    assert envelope.error is None
    assert [row["code"] for row in envelope.data] == ["005930"]
    assert envelope.data[0]["buy_grade"] == "BUY"


async def test_get_ratings_empty_codes_returns_empty_list():
    envelope = await ratings_api.get_ratings(codes="")

    assert envelope.error is None
    assert envelope.data == []


# --- GET /api/ratings/positions -----------------------------------------------------

async def test_get_positions_ratings_ok():
    envelope = await ratings_api.get_positions_ratings()

    assert envelope.error is None
    assert envelope.data == []


# --- POST /api/ratings/compute -------------------------------------------------------

async def test_compute_unsupported_us_ticker_skips_scoring(monkeypatch, service_session):
    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("compute_buy_ratings must not be called for UNSUPPORTED codes")

    monkeypatch.setattr(ratings_api, "compute_buy_ratings", _must_not_be_called)

    envelope = await ratings_api.compute_rating(code="AAPL", session=service_session)

    assert envelope.error is None
    assert envelope.data == {
        "code": "AAPL",
        "status": "UNSUPPORTED",
        "buy_grade": None,
        "score": None,
        "percentile": None,
        "weakest_group": None,
    }


async def test_compute_kr_code_upserts_and_returns_row(monkeypatch, service_session):
    monkeypatch.setattr(ratings_api, "compute_buy_ratings", _fake_compute_buy_ratings)
    monkeypatch.setattr(
        ratings_api, "resolve_rating_strategy", lambda name: (_strategy(), None)
    )
    spy = AsyncMock(side_effect=store.upsert_stock_ratings)
    monkeypatch.setattr(store, "upsert_stock_ratings", spy)

    envelope = await ratings_api.compute_rating(code="005930", session=service_session)

    assert envelope.error is None
    assert envelope.data == {
        "code": "005930",
        "status": "OK",
        "buy_grade": "BUY",
        "score": 0.6,
        "percentile": 0.7,
        "weakest_group": None,
    }
    spy.assert_awaited_once()


async def test_compute_returns_409_when_lock_held(service_session):
    await store.RATING_LOCK.acquire()
    try:
        response = await ratings_api.compute_rating(code="005930", session=service_session)
    finally:
        store.RATING_LOCK.release()

    assert isinstance(response, JSONResponse)
    assert response.status_code == 409


# --- PATCH /api/settings (rating_strategy_name) --------------------------------------

async def test_patch_settings_persists_rating_strategy_name(service_session):
    await settings_api.patch_settings(
        {"rating_strategy_name": "qlab_alpha_v2"}, session=service_session
    )

    envelope = await settings_api.get_settings(session=service_session)

    assert envelope.data.rating_strategy_name == "qlab_alpha_v2"
