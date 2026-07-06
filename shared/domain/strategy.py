"""Strategy and backtest domain models."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class FactorWeight(BaseModel):
    factor: str
    weight: float
    transform: Literal["RAW", "ZSCORE", "RANK"]


class FilterRule(BaseModel):
    field: str
    op: Literal["GT", "GTE", "LT", "LTE", "BETWEEN"]
    value: float | list[float]


class GroupFactor(BaseModel):
    """One factor inside a scoring group. ``higher_is_better=False`` inverts it
    (e.g. PER/PBR — a low value scores high)."""

    factor: str
    higher_is_better: bool = True


class FactorGroup(BaseModel):
    """A weighted factor group in the qlab_alpha_v2 composite (Layer A)."""

    name: str
    weight: float
    factors: list[GroupFactor]


class StrategyDefinition(BaseModel):
    """Parameterized scoring equation, serializable to and from YAML.

    Two scoring modes:
    - flat (default): ``factors`` = weighted Σ wᵢ·transform(rawᵢ). Unchanged.
    - grouped (qlab_alpha_v2): when ``groups`` is set, the composite scorer
      (research.backtest.composite) is used with robust preprocessing and
      coverage handling. ``factors`` may then stay empty.
    """

    name: str
    description: str
    universe: Literal[
        "KOSPI200",
        "KOSDAQ150",
        "KOSPI_ALL",
        "KOSDAQ_ALL",
        "NASDAQ100",
        "CUSTOM",
    ]
    rebalance_freq: Literal["MONTHLY", "QUARTERLY", "YEARLY"]
    factors: list[FactorWeight]
    filters: list[FilterRule]
    top_n: int
    start_date: date
    end_date: date
    groups: list[FactorGroup] | None = None
    min_groups: int = 5
    winsor_pct: float = 0.01
    clip_z: float = 3.0
