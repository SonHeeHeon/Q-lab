"""/api/ratings 라우터 테스트 (Phase T5, 2-슬리브 T10): 조회 3종 + 온디맨드 재계산.

store.py는 shared.db.session.service_session을 모듈 스코프로 import했으므로
in-memory 테스트 DB(service_sessionmaker)로 monkeypatch 해야 실제
data/service.db를 건드리지 않는다 (test_rating_batch.py와 동일 패턴).
라우터 함수를 FastAPI 없이 직접 호출해 Depends(session)는 fixture 값을
그대로 넘긴다 (test_proposals_api.py와 동일 패턴).

``ratings_api.etf_universe_codes``(ETF_KR 유니버스 유도, 실제 research.db를
sqlite3로 직결)는 기본적으로 빈 집합을 반환하도록 monkeypatch한다 — 실제
DB를 절대 건드리지 않기 위함이며, ETF 디스패치를 검증하는 테스트만 개별적으로
override한다.
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
    # ETF_KR 유니버스 유도(get_universe, 실제 research.db 직결)를 기본적으로
    # 빈 집합으로 막아 실제 DB를 건드리지 않는다 — ETF 디스패치 테스트만 override.
    monkeypatch.setattr(
        ratings_api, "etf_universe_codes", AsyncMock(return_value=set())
    )


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
    # /compute 는 저장된 DB 행을 그대로 반환한다(GET /api/ratings 와 동일 스키마):
    # strategy_name/as_of 를 포함하며, updated_at 은 타임스탬프라 존재만 확인한다.
    data = envelope.data
    assert {k: data[k] for k in ("code", "status", "buy_grade", "score", "percentile", "weakest_group")} == {
        "code": "005930",
        "status": "OK",
        "buy_grade": "BUY",
        "score": 0.6,
        "percentile": 0.7,
        "weakest_group": None,
    }
    assert data["strategy_name"] == "ratings_api_test"
    assert data["as_of"] == "2026-07-24"
    assert "updated_at" in data
    spy.assert_awaited_once()


async def test_compute_etf_code_routes_to_etf_strategy_with_rank_remap(
    monkeypatch, service_session
):
    # 069500이 ETF_KR 유니버스에 속한다고 판정되면 stock 경로가 아니라 ETF
    # 슬리브 전략 + 순위 기반 remap(rating_batch.remap_etf_grades, 실제 함수 사용)
    # 을 거쳐야 한다.
    monkeypatch.setattr(
        ratings_api,
        "etf_universe_codes",
        AsyncMock(return_value={"069500", "091160", "091170"}),
    )

    def _fake_resolve_etf_strategy(setting_value):
        del setting_value
        return (
            _strategy(
                name="etf_rotation_kr", universe="ETF_KR",
                rebalance_freq="MONTHLY", top_n=3,
            ),
            None,
        )

    monkeypatch.setattr(ratings_api, "resolve_etf_strategy", _fake_resolve_etf_strategy)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("stock resolve_rating_strategy must not be called for ETF codes")

    monkeypatch.setattr(ratings_api, "resolve_rating_strategy", _must_not_be_called)

    def _fake_compute_etf(strategy, extra_codes=(), *, as_of=None, db_path=None):
        del extra_codes, as_of, db_path
        ratings = [
            BuyRating(code="069500", status="OK", buy_grade=None, score=1.0, percentile=None, weakest_group=None),
            BuyRating(code="091160", status="OK", buy_grade=None, score=0.5, percentile=None, weakest_group=None),
            BuyRating(code="091170", status="OK", buy_grade=None, score=0.1, percentile=None, weakest_group=None),
        ]
        return BuyRatingsResult(
            as_of="2026-07-24", strategy_name=strategy.name,
            universe_size=len(ratings), ratings=ratings, warnings=[],
        )

    monkeypatch.setattr(ratings_api, "compute_buy_ratings", _fake_compute_etf)

    envelope = await ratings_api.compute_rating(code="069500", session=service_session)

    assert envelope.error is None
    data = envelope.data
    assert data["code"] == "069500"
    assert data["strategy_name"] == "etf_rotation_kr"
    assert data["buy_grade"] == "STRONG_BUY"  # rank1(최고 score) remap
    assert data["percentile"] == 1.0


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


# --- GET /api/ratings/status (2-슬리브 T10 가산 필드) ---------------------------------

async def test_status_carries_both_strategy_names(service_session):
    """/status는 기존 strategy_name(주식)에 더해 etf_strategy_name을 가산적으로
    노출한다. Setting 미저장 시 각자의 기본값 폴백.
    verifier 커버리지 갭 지적으로 추가 — 라이브 curl로만 확인되던 필드."""
    from types import SimpleNamespace

    fake_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    envelope = await ratings_api.get_ratings_status(
        request=fake_request, session=service_session
    )

    assert envelope.error is None
    data = envelope.data
    assert data["strategy_name"]  # 기본값(value_v1) 폴백
    assert data["etf_strategy_name"] == "etf_rotation_kr"
    assert data["scheduler_running"] is False
