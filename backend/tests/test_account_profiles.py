"""account_profiles 시드·검증 로직."""
from __future__ import annotations

import pytest

from backend.app.services.accounts.profiles import (
    ACCOUNT_KEYS,
    default_sleeves,
    validate_sleeves,
)


def test_account_keys_cover_seven():
    assert ACCOUNT_KEYS == [
        "KIS:PAPER", "KIS:REAL", "KIS:ISA",
        "KIS:DC", "KIS:IRP", "KIS:PENSION", "TOSS:MAIN",
    ]


def test_default_sleeves_weights_sum_to_one():
    for key in ACCOUNT_KEYS:
        sleeves = default_sleeves(key)
        assert sleeves, key
        assert sum(s["weight"] for s in sleeves) == pytest.approx(1.0)


def test_dc_default_contains_hold_sleeve():
    kinds = {s["type"] for s in default_sleeves("KIS:DC")}
    assert kinds == {"strategy", "hold"}


def test_validate_sleeves_rejects_bad_sum():
    with pytest.raises(ValueError):
        validate_sleeves([
            {"type": "strategy", "name": "etf_rotation_kr", "weight": 0.5},
        ])


def test_validate_sleeves_rejects_unknown_type():
    with pytest.raises(ValueError):
        validate_sleeves([{"type": "magic", "weight": 1.0}])


def test_validate_sleeves_rejects_disallowed_universe_for_pension():
    # 연금저축은 개별주식 전략(KOSPI200 유니버스) 불가
    with pytest.raises(ValueError):
        validate_sleeves(
            [{"type": "strategy", "name": "value_v1", "weight": 1.0}],
            profile_type="PENSION",
        )


def test_validate_sleeves_rejects_risk_code_for_dc_hold():
    # DC/IRP hold 코드는 안전(safe) allowlist만 — 069500은 risk 분류
    with pytest.raises(ValueError):
        validate_sleeves(
            [
                {"type": "strategy", "name": "dc_risk_rotation_kr", "weight": 0.68},
                {"type": "hold", "code": "069500", "weight": 0.32},
            ],
            profile_type="DC",
        )


def test_validate_sleeves_accepts_dc_default_composition():
    out = validate_sleeves(
        [
            {"type": "strategy", "name": "dc_risk_rotation_kr", "weight": 0.68},
            {"type": "hold", "code": "153130", "weight": 0.32},
        ],
        profile_type="DC",
    )
    assert len(out) == 2


def test_available_sleeves_pension_filters_universe():
    from backend.app.services.accounts.profiles import available_sleeves

    names = {s["name"] for s in available_sleeves("PENSION")}
    assert "dc_risk_rotation_kr" in names
    assert "value_v1" not in names  # KOSPI200(개별주식) 제외


def test_validate_sleeves_normalizes_rounding():
    out = validate_sleeves([
        {"type": "strategy", "name": "etf_rotation_kr", "weight": 0.333},
        {"type": "strategy", "name": "etf_rotation_us", "weight": 0.667},
    ])
    assert sum(s["weight"] for s in out) == pytest.approx(1.0)
