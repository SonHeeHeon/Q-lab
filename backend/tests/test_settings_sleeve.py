"""/api/settings 2-슬리브 설정 키(etf_strategy_name, sleeve_etf_weight) 테스트 (T3).

test_api_ratings.py::test_patch_settings_persists_rating_strategy_name과 동일하게
라우터 함수를 FastAPI 없이 직접 호출해 Depends(session)에 fixture 값을 그대로
넘긴다.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import backend.app.api.settings as settings_api


# --- GET /api/settings 기본값 --------------------------------------------------------


async def test_get_settings_defaults_etf_sleeve(service_session):
    envelope = await settings_api.get_settings(session=service_session)

    assert envelope.data.etf_strategy_name == "etf_rotation_kr"
    assert envelope.data.sleeve_etf_weight == 0.3


# --- PATCH round-trip ----------------------------------------------------------------


async def test_patch_settings_persists_etf_sleeve_keys(service_session):
    await settings_api.patch_settings(
        {"etf_strategy_name": "etf_rotation_kr", "sleeve_etf_weight": "0.4"},
        session=service_session,
    )

    envelope = await settings_api.get_settings(session=service_session)

    assert envelope.data.etf_strategy_name == "etf_rotation_kr"
    assert envelope.data.sleeve_etf_weight == 0.4


# --- parse_sleeve_weight 클램프/폴백 ---------------------------------------------------


def test_parse_sleeve_weight_fallback_on_invalid():
    assert settings_api.parse_sleeve_weight("abc") == 0.3


def test_parse_sleeve_weight_clamps_high():
    assert settings_api.parse_sleeve_weight("1.7") == 1.0


def test_parse_sleeve_weight_clamps_low():
    assert settings_api.parse_sleeve_weight("-1") == 0.0


# --- PATCH validation: 잘못된 sleeve_etf_weight는 거부 -------------------------------


async def test_patch_settings_rejects_invalid_sleeve_weight(service_session):
    with pytest.raises(HTTPException) as exc_info:
        await settings_api.patch_settings(
            {"sleeve_etf_weight": "abc"}, session=service_session
        )
    assert exc_info.value.status_code == 400


async def test_patch_settings_rejects_out_of_range_sleeve_weight(service_session):
    with pytest.raises(HTTPException) as exc_info:
        await settings_api.patch_settings(
            {"sleeve_etf_weight": "1.5"}, session=service_session
        )
    assert exc_info.value.status_code == 400
