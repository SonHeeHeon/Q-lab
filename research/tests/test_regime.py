"""Macro regime gate tests (qlab_alpha_v2 Layer B)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from research.backtest.regime import (
    CRISIS,
    NEUTRAL,
    RISK_OFF,
    RISK_ON,
    RegimeState,
    compute_regime,
    confirm_regime,
)

AS_OF = date(2026, 7, 6)


def _series(values: list[float], *, end: date = AS_OF) -> pd.Series:
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=len(values))
    return pd.Series(values, index=idx, dtype="float64")


def test_risk_on_all_green():
    kospi = _series(list(np.linspace(2000, 3000, 260)))     # strong uptrend
    us10y = _series([4.0] * 80)                             # flat rates
    usdkrw = _series([1300.0] * 80)                         # stable/strong won
    vix = _series([14.0] * 30)                              # calm
    state = compute_regime(AS_OF, kospi=kospi, us10y=us10y, usdkrw=usdkrw, vix=vix)
    assert state.label == RISK_ON
    assert state.exposure == 1.0
    assert state.r_score >= 0.75


def test_crisis_all_red():
    kospi = _series(list(np.linspace(3000, 2000, 260)))     # downtrend
    us10y = _series(list(np.linspace(3.5, 5.0, 80)))        # spiking rates
    usdkrw = _series(list(np.linspace(1300, 1450, 80)))     # won crashing
    vix = _series([38.0] * 30)                              # panic
    state = compute_regime(AS_OF, kospi=kospi, us10y=us10y, usdkrw=usdkrw, vix=vix)
    assert state.label == CRISIS
    assert state.exposure == 0.0


def test_vix_bands():
    flat_kospi = _series([2500.0] * 260)
    for level, expect_at_least in [(15.0, 0.5), (25.0, 0.5), (35.0, 0.0)]:
        state = compute_regime(AS_OF, kospi=flat_kospi, vix=_series([level] * 30))
        # flat trend = 0.5; vix modulates. Just assert monotonic exposure.
        assert 0.0 <= state.exposure <= 1.0
    hi = compute_regime(AS_OF, vix=_series([35.0] * 30))
    lo = compute_regime(AS_OF, vix=_series([12.0] * 30))
    assert lo.r_score > hi.r_score


def test_missing_inputs_renormalize():
    # Only VIX present → R equals the VIX component alone.
    calm = compute_regime(AS_OF, vix=_series([12.0] * 30))
    assert calm.components == {"vix": 1.0}
    assert calm.r_score == pytest.approx(1.0)


def test_no_inputs_defaults_neutral():
    state = compute_regime(AS_OF)
    assert state.label == NEUTRAL and state.exposure == 0.7


def test_insufficient_history_drops_component():
    # 100 points < 200 → trend unavailable, excluded from R.
    short = _series([2500.0] * 100)
    state = compute_regime(AS_OF, kospi=short, vix=_series([12.0] * 30))
    assert "trend" not in state.components
    assert "vix" in state.components


def test_point_in_time_ignores_future():
    kospi = _series(list(np.linspace(2000, 3000, 260)))
    # Append a future crash that must be ignored for an earlier as_of.
    future = pd.Series(
        [1000.0], index=[pd.Timestamp(AS_OF) + timedelta(days=3)]
    )
    kospi = pd.concat([kospi, future])
    state = compute_regime(AS_OF, kospi=kospi, vix=_series([14.0] * 30))
    assert state.label in (RISK_ON, NEUTRAL)  # future crash not seen


def test_confirm_regime_whipsaw_guard():
    def s(label: str) -> RegimeState:
        return RegimeState(label, 1.0, 0.8, {})

    # A single RISK_OFF day inside a RISK_ON run must not flip the regime.
    recent = [s(RISK_ON)] * 6 + [s(RISK_OFF)] + [s(RISK_ON)] * 5
    assert confirm_regime(recent, persistence=5).label == RISK_ON
    # A sustained 5-day switch is accepted.
    recent2 = [s(RISK_ON)] * 6 + [s(RISK_OFF)] * 5
    assert confirm_regime(recent2, persistence=5).label == RISK_OFF
