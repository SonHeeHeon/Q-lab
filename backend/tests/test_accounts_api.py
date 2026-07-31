"""계좌 API 핵심 로직: 잠금 강제 + 토글/비중 갱신."""
from __future__ import annotations

import pytest

from backend.app.api.accounts import AccountPatch, LiveLockError, apply_account_patch


class _FakeProfile:
    def __init__(self, key: str):
        self.account_key = key
        self.profile_type = "PERSONAL"
        self.quant_enabled = False
        self.sleeves_json = "[]"


def test_real_account_on_blocked_while_locked():
    profile = _FakeProfile("KIS:REAL")
    with pytest.raises(LiveLockError):
        apply_account_patch(
            profile, AccountPatch(quant_enabled=True), live_unlocked=False
        )


def test_paper_account_on_allowed_while_locked():
    profile = _FakeProfile("KIS:PAPER")
    apply_account_patch(
        profile, AccountPatch(quant_enabled=True), live_unlocked=False
    )
    assert profile.quant_enabled is True


def test_real_account_on_allowed_when_unlocked():
    profile = _FakeProfile("KIS:REAL")
    apply_account_patch(
        profile, AccountPatch(quant_enabled=True), live_unlocked=True
    )
    assert profile.quant_enabled is True


def test_off_always_allowed():
    profile = _FakeProfile("KIS:REAL")
    profile.quant_enabled = True
    apply_account_patch(
        profile, AccountPatch(quant_enabled=False), live_unlocked=False
    )
    assert profile.quant_enabled is False


def test_sleeves_patch_validates_sum():
    profile = _FakeProfile("KIS:PAPER")
    with pytest.raises(ValueError):
        apply_account_patch(
            profile,
            AccountPatch(sleeves=[{"type": "strategy", "name": "x", "weight": 0.4}]),
            live_unlocked=False,
        )


def test_profile_type_patch_validates():
    profile = _FakeProfile("KIS:REAL")
    with pytest.raises(ValueError):
        apply_account_patch(
            profile, AccountPatch(profile_type="WEIRD"), live_unlocked=True
        )
    apply_account_patch(profile, AccountPatch(profile_type="ISA"), live_unlocked=False)
    assert profile.profile_type == "ISA"
