"""qlab_alpha_v2 Layer B — macro regime gate.

Turns four macro series into a market-state score R∈[0,1] and an equity
exposure (0–100%), so the composite alpha (Layer A) is scaled by how risk-on
the environment is instead of always running fully invested:

    R = 0.40·Trend + 0.20·Rate + 0.20·FX + 0.20·VIX

    Trend : KOSPI close vs its 200-day MA        (uptrend → 1)
    Rate  : US 10Y yield 3-month change          (falling/flat → 1, spiking → 0)
    FX    : USD/KRW vs its 60-day MA              (won strong → 1)
    VIX   : level bands (<20 → 1, 20–30 → 0.5, ≥30 → 0)

    R ≥ 0.75 RISK_ON   → 100% exposure
    R ≥ 0.50 NEUTRAL   → 70%
    R ≥ 0.25 RISK_OFF  → 40%
    else     CRISIS    → 0%  (no new buys; existing positions ride stop-loss)

Pure/pandas — series are passed in, so it is deterministic and unit-testable.
Point-in-time: every reader uses values on or before ``as_of``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date

import numpy as np
import pandas as pd

RISK_ON = "RISK_ON"
NEUTRAL = "NEUTRAL"
RISK_OFF = "RISK_OFF"
CRISIS = "CRISIS"

_EXPOSURE = {RISK_ON: 1.0, NEUTRAL: 0.7, RISK_OFF: 0.4, CRISIS: 0.0}


@dataclass(frozen=True)
class RegimeState:
    label: str
    exposure: float
    r_score: float
    components: dict[str, float]


def _as_of_slice(series: pd.Series | None, as_of: Date) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype="float64")
    s = pd.to_numeric(series, errors="coerce").dropna()
    s.index = pd.to_datetime(s.index)
    return s[s.index <= pd.Timestamp(as_of)]


def _trend_score(kospi: pd.Series | None, as_of: Date) -> float | None:
    s = _as_of_slice(kospi, as_of)
    if len(s) < 200:
        return None
    last = float(s.iloc[-1])
    ma200 = float(s.tail(200).mean())
    if ma200 <= 0:
        return None
    # ±5% band around the MA maps to [0,1] via tanh, then rescaled.
    dev = (last / ma200) - 1.0
    return float((np.tanh(dev / 0.05) + 1.0) / 2.0)


def _rate_score(us10y: pd.Series | None, as_of: Date) -> float | None:
    s = _as_of_slice(us10y, as_of)
    if len(s) < 63:
        return None
    now = float(s.iloc[-1])
    prior = float(s.iloc[-63])  # ~3 trading months
    change_pp = now - prior  # yield points
    # +0.5pp spike → 0, −0.5pp fall → 1, flat → 0.5.
    return float(np.clip(0.5 - change_pp, 0.0, 1.0))


def _fx_score(usdkrw: pd.Series | None, as_of: Date) -> float | None:
    s = _as_of_slice(usdkrw, as_of)
    if len(s) < 60:
        return None
    last = float(s.iloc[-1])
    ma60 = float(s.tail(60).mean())
    if ma60 <= 0:
        return None
    dev = (last / ma60) - 1.0  # won weakening = USDKRW above MA = risk-off
    return float(np.clip(1.0 - dev / 0.03, 0.0, 1.0))


def _vix_score(vix: pd.Series | None, as_of: Date) -> float | None:
    s = _as_of_slice(vix, as_of)
    if s.empty:
        return None
    level = float(s.iloc[-1])
    if level < 20:
        return 1.0
    if level < 30:
        return 0.5
    return 0.0


_WEIGHTS = {"trend": 0.40, "rate": 0.20, "fx": 0.20, "vix": 0.20}


def compute_regime(
    as_of: Date,
    *,
    kospi: pd.Series | None = None,
    us10y: pd.Series | None = None,
    usdkrw: pd.Series | None = None,
    vix: pd.Series | None = None,
) -> RegimeState:
    """Regime state at ``as_of``. Missing inputs are dropped and the remaining
    component weights are renormalized; with nothing available, NEUTRAL."""
    raw = {
        "trend": _trend_score(kospi, as_of),
        "rate": _rate_score(us10y, as_of),
        "fx": _fx_score(usdkrw, as_of),
        "vix": _vix_score(vix, as_of),
    }
    components = {name: value for name, value in raw.items() if value is not None}
    if not components:
        return RegimeState(NEUTRAL, _EXPOSURE[NEUTRAL], 0.5, {})

    weight_sum = sum(_WEIGHTS[name] for name in components)
    r = sum(_WEIGHTS[name] * value for name, value in components.items()) / weight_sum

    if r >= 0.75:
        label = RISK_ON
    elif r >= 0.50:
        label = NEUTRAL
    elif r >= 0.25:
        label = RISK_OFF
    else:
        label = CRISIS
    return RegimeState(label, _EXPOSURE[label], float(r), components)


def confirm_regime(recent: list[RegimeState], *, persistence: int = 5) -> RegimeState:
    """Whipsaw guard: only accept a new label once it has held for ``persistence``
    consecutive days; otherwise keep the last confirmed label. ``recent`` is
    oldest→newest and must be non-empty."""
    if not recent:
        raise ValueError("recent must be non-empty")
    confirmed = recent[0]
    run_label = recent[0].label
    run_len = 1
    for state in recent[1:]:
        if state.label == run_label:
            run_len += 1
        else:
            run_label = state.label
            run_len = 1
        if run_len >= persistence:
            confirmed = state
    # If the newest run already reached persistence, `confirmed` is newest.
    # Otherwise fall back to the most recent state whose run confirmed.
    return confirmed
