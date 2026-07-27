"""
Module: backend.tests.test_kis_etf_components

Role:
    Verify KISRestClient.get_etf_components (T2):
      - Normalizes a mocked KIS output2 constituent list into
        {code, name, weight, raw} dicts.
      - Returns [] when output2 is empty or missing.
      - zfills the requested ETF code to 6 digits when calling _request.

_request is monkeypatched with an AsyncMock so no network call is made.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from backend.app.services.kis.rest_client import KISRestClient
from shared.domain.account import AccountType


@pytest.mark.asyncio
async def test_get_etf_components_normalizes_output2(monkeypatch):
    client = KISRestClient()
    fake_payload = {
        "rt_cd": "0",
        "output2": [
            {
                "stck_shrn_iscd": "005930",
                "hts_kor_isnm": "삼성전자",
                "etf_cnfg_issu_avls_rlim": "12.34",
            },
            {
                "stck_shrn_iscd": "000660",
                "hts_kor_isnm": "SK하이닉스",
                "etf_cnfg_issu_avls_rlim": "5.67",
            },
        ],
    }
    request_mock = AsyncMock(return_value=(fake_payload, {}))
    monkeypatch.setattr(client, "_request", request_mock)

    components = await client.get_etf_components(AccountType.PAPER, "69500")

    assert len(components) == 2
    first, second = components
    assert first["code"] == "005930"
    assert first["name"] == "삼성전자"
    assert first["weight"] == Decimal("12.34")
    assert first["raw"] == fake_payload["output2"][0]
    assert second["code"] == "000660"
    assert second["name"] == "SK하이닉스"
    assert second["weight"] == Decimal("5.67")

    request_mock.assert_awaited_once()
    _method, _account_type, path = request_mock.await_args.args
    kwargs = request_mock.await_args.kwargs
    assert path == "/uapi/domestic-stock/v1/quotations/inquire-etf-component-stock-price"
    assert kwargs["tr_id"] == "FHKST121600C0"
    assert kwargs["params"]["FID_INPUT_ISCD"] == "069500"
    assert kwargs["params"]["FID_COND_MRKT_DIV_CODE"] == "J"
    assert kwargs["params"]["FID_COND_SCR_DIV_CODE"] == "11216"


@pytest.mark.asyncio
async def test_get_etf_components_missing_output2_returns_empty(monkeypatch):
    client = KISRestClient()
    request_mock = AsyncMock(return_value=({"rt_cd": "0"}, {}))
    monkeypatch.setattr(client, "_request", request_mock)

    components = await client.get_etf_components(AccountType.PAPER, "069500")

    assert components == []


@pytest.mark.asyncio
async def test_get_etf_components_empty_output2_returns_empty(monkeypatch):
    client = KISRestClient()
    request_mock = AsyncMock(return_value=({"rt_cd": "0", "output2": []}, {}))
    monkeypatch.setattr(client, "_request", request_mock)

    components = await client.get_etf_components(AccountType.PAPER, "069500")

    assert components == []


@pytest.mark.asyncio
async def test_get_etf_components_zfills_code(monkeypatch):
    client = KISRestClient()
    request_mock = AsyncMock(return_value=({"rt_cd": "0", "output2": []}, {}))
    monkeypatch.setattr(client, "_request", request_mock)

    await client.get_etf_components(AccountType.REAL, "42")

    kwargs = request_mock.await_args.kwargs
    assert kwargs["params"]["FID_INPUT_ISCD"] == "000042"
