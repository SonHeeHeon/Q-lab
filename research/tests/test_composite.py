"""qlab_alpha_v2 grouped composite scorer tests (Layer A of the equation)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.backtest.composite import (
    GroupFactorSpec,
    GroupSpec,
    composite_score,
    group_score,
    robust_zscore,
)


def test_robust_zscore_winsorizes_outlier():
    # One 100x outlier must not blow up the standardization of the rest.
    s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 1000.0])
    z = robust_zscore(s, winsor_pct=0.1)
    assert z.iloc[-1] == pytest.approx(z.max())  # outlier at the cap, finite
    assert z.abs().max() <= 3.0                    # clipped
    assert abs(z.iloc[:-1].mean()) < 1.0           # bulk stays sane


def test_robust_zscore_preserves_nan_and_zero_variance():
    z = robust_zscore(pd.Series([5.0, np.nan, 5.0, 5.0]))
    assert pd.isna(z.iloc[1])
    assert (z.dropna() == 0.0).all()  # no dispersion → all zeros


def test_group_score_sign_alignment():
    # PER lower-is-better must invert: the cheapest name scores highest.
    frame = pd.DataFrame({"PER": [5.0, 10.0, 20.0]}, index=["a", "b", "c"])
    gs = group_score(frame, (GroupFactorSpec("PER", higher_is_better=False),))
    assert gs["a"] > gs["b"] > gs["c"]


def test_group_score_averages_available_factors_only():
    frame = pd.DataFrame(
        {"ROE": [0.2, 0.1, 0.05], "ROA": [0.1, np.nan, 0.02]},
        index=["a", "b", "c"],
    )
    gs = group_score(
        frame, (GroupFactorSpec("ROE"), GroupFactorSpec("ROA"), GroupFactorSpec("MISSING"))
    )
    # 'b' has only ROE → its group score equals ROE's z (MISSING/ROA skipped).
    assert gs.notna().all()
    assert gs["a"] > gs["c"]


def _two_groups() -> tuple[GroupSpec, ...]:
    return (
        GroupSpec("Value", 0.5, (GroupFactorSpec("PER", higher_is_better=False),)),
        GroupSpec("Quality", 0.5, (GroupFactorSpec("ROE"),)),
    )


def test_composite_min_groups_drops_thin_coverage():
    frame = pd.DataFrame(
        {"PER": [5.0, 10.0, np.nan], "ROE": [0.2, np.nan, 0.1]},
        index=["a", "b", "c"],
    )
    score = composite_score(frame, _two_groups(), min_groups=2)
    assert score.notna().sum() == 1  # only 'a' has both groups
    assert not pd.isna(score["a"])
    assert pd.isna(score["b"]) and pd.isna(score["c"])


def test_composite_renormalizes_available_weights():
    frame = pd.DataFrame(
        {"PER": [5.0, 10.0, 20.0], "ROE": [0.2, 0.1, 0.05]},
        index=["a", "b", "c"],
    )
    score = composite_score(frame, _two_groups(), min_groups=1)
    # All present, equal weights → 'a' (cheap + high ROE) tops, 'c' bottoms.
    assert score["a"] > score["b"] > score["c"]


def test_composite_coverage_penalty_favors_full_data():
    # Two stocks with identical directional signal; one has 1 group, one has 2.
    # The fuller-coverage stock must score higher (sqrt(2/2) vs sqrt(1/2)).
    frame = pd.DataFrame(
        {
            "PER": [5.0, 5.0, 20.0, 20.0],   # a,b cheap; c,d expensive
            "ROE": [0.2, np.nan, 0.05, np.nan],
        },
        index=["a", "b", "c", "d"],
    )
    score = composite_score(frame, _two_groups(), min_groups=1)
    assert score["a"] > score["b"]  # same value+quality signal, a has more coverage
