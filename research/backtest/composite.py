"""qlab_alpha_v2 grouped composite scorer (Layer A of the equation).

Extends the flat ``Σ wᵢ·transform(rawᵢ)`` score with a group structure and
robust preprocessing that the audit flagged as missing:

- **winsorize → z-score → clip**: caps outliers before standardizing, so one
  extreme PER no longer dominates the whole cross-section.
- **group means**: factors are averaged within a group (Value, Quality, …)
  before groups are combined, so a group with many factors doesn't outvote a
  group with one.
- **availability renormalization + coverage penalty**: a stock is scored on
  whatever groups it has data for, renormalized by the available group weights,
  then multiplied by ``sqrt(available_groups / total_groups)`` so thin-coverage
  names are penalized instead of silently competing on partial data (the old
  ``min_count=1`` bias). Stocks below ``min_groups`` available groups are
  dropped rather than scored on too little.

Pure/pandas only — no DB or IO — so it is deterministic and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GroupFactorSpec:
    """One factor inside a group. ``higher_is_better=False`` negates its z-score
    (e.g. PER/PBR: a low value is good)."""

    name: str
    higher_is_better: bool = True


@dataclass(frozen=True)
class GroupSpec:
    name: str
    weight: float
    factors: tuple[GroupFactorSpec, ...]


def robust_zscore(
    series: pd.Series,
    *,
    winsor_pct: float = 0.01,
    clip_z: float = 3.0,
) -> pd.Series:
    """Cross-sectional z-score after winsorizing tails and clipping the result.

    NaN inputs stay NaN. With <2 valid observations everything valid maps to 0
    (no dispersion to standardize against).
    """
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.dropna()
    if len(valid) < 2:
        return numeric.where(numeric.isna(), 0.0)

    lower = valid.quantile(winsor_pct)
    upper = valid.quantile(1.0 - winsor_pct)
    winsorized = numeric.clip(lower, upper)

    std = winsorized.std(ddof=0)
    if std == 0 or pd.isna(std):
        return numeric.where(numeric.isna(), 0.0)
    z = (winsorized - winsorized.mean()) / std
    return z.clip(-clip_z, clip_z)


def group_score(
    frame: pd.DataFrame,
    factors: tuple[GroupFactorSpec, ...],
    *,
    winsor_pct: float = 0.01,
    clip_z: float = 3.0,
) -> pd.Series:
    """Mean of robust z-scores of a group's available factors (sign-aligned).

    Returns NaN for a stock only when it has no data for any factor in the
    group. Direction is normalized so a higher group score is always "better".
    """
    columns: list[pd.Series] = []
    for spec in factors:
        if spec.name not in frame.columns:
            continue
        z = robust_zscore(frame[spec.name], winsor_pct=winsor_pct, clip_z=clip_z)
        columns.append(z if spec.higher_is_better else -z)
    if not columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    stacked = pd.concat(columns, axis=1)
    return stacked.mean(axis=1)  # skipna: mean over the factors present per stock


def group_score_frame(
    frame: pd.DataFrame,
    groups: tuple[GroupSpec, ...],
    *,
    winsor_pct: float = 0.01,
    clip_z: float = 3.0,
) -> pd.DataFrame:
    """Per-group scores (one column per ``GroupSpec.name``) before weighting.

    Column g, row i = ``group_score`` of group g for stock i (NaN when the
    stock has no data for any factor in that group). This is the per-group
    breakdown that ``composite_score`` collapses into one number; exposing it
    lets a caller name a stock's weakest (lowest-scoring) group.
    """
    return pd.DataFrame(
        {
            spec.name: group_score(
                frame, spec.factors, winsor_pct=winsor_pct, clip_z=clip_z
            )
            for spec in groups
        },
        index=frame.index,
    )


def composite_from_groups(
    group_frame: pd.DataFrame,
    groups: tuple[GroupSpec, ...],
    *,
    min_groups: int = 5,
) -> pd.Series:
    """Collapse a per-group score frame (``group_score_frame``) into the final
    composite score.

    Split out of ``composite_score`` so a caller that also needs the per-group
    breakdown reuses the same group scores instead of recomputing them.

    S(i) = [ Σ_{g∈avail} w_g·G_g(i) / Σ_{g∈avail} w_g ] × sqrt(|avail| / n_groups),
    with S(i)=NaN when |avail(i)| < ``min_groups``.
    """
    if not groups or group_frame.shape[1] == 0:
        return pd.Series(np.nan, index=group_frame.index, dtype="float64")

    weights = pd.Series({spec.name: float(spec.weight) for spec in groups})

    present = group_frame.notna()
    avail_count = present.sum(axis=1)
    avail_weight = present.mul(weights, axis=1).sum(axis=1)
    weighted_sum = group_frame.mul(weights, axis=1).sum(axis=1, min_count=1)

    base = weighted_sum / avail_weight.replace(0.0, np.nan)
    coverage_penalty = np.sqrt(avail_count / float(len(groups)))
    score = base * coverage_penalty
    score[avail_count < min_groups] = np.nan
    return score


def composite_score(
    frame: pd.DataFrame,
    groups: tuple[GroupSpec, ...],
    *,
    min_groups: int = 5,
    winsor_pct: float = 0.01,
    clip_z: float = 3.0,
) -> pd.Series:
    """Availability-renormalized, coverage-penalized weighted group composite.

    S(i) = [ Σ_{g∈avail} w_g·G_g(i) / Σ_{g∈avail} w_g ] × sqrt(|avail| / n_groups),
    with S(i)=NaN when |avail(i)| < ``min_groups``.
    """
    if not groups:
        return pd.Series(np.nan, index=frame.index, dtype="float64")

    gdf = group_score_frame(frame, groups, winsor_pct=winsor_pct, clip_z=clip_z)
    return composite_from_groups(gdf, groups, min_groups=min_groups)
