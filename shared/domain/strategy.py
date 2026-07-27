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
        "KOSPI_TOP100",
        "KOSDAQ150",
        "KOSPI_ALL",
        "KOSDAQ_ALL",
        "NASDAQ100",
        "US_LARGE",
        "ETF_KR",
        "ETF_US",
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
    # Layer B: when true, scale invested capital by the macro regime exposure
    # (0–100%); the rest is held as cash. CRISIS (0%) fully de-risks.
    use_regime: bool = False
    # REBALANCE: regime sampled only on rebalance days (v1 behavior — proven
    # ineffective for drawdown control with quarterly rebalances).
    # MONTHLY: additionally checked at each month start between rebalances
    # with 5-day label persistence; positions are scaled up/down to the
    # confirmed exposure without re-scoring.
    regime_check: Literal["REBALANCE", "MONTHLY"] = "REBALANCE"
    # Robustness option: execute rebalance trades N trading days after the
    # signal day (0 = same-day close, the optimistic default). lag=1 removes
    # the signal-day-close fill assumption entirely.
    execution_lag_days: int = 0

    # --- Intra-period trade rules (Phase 4.2). All default OFF; each must be
    # backtest-validated before use in the live proposal pipeline. ---
    # Sell a holding back to its base weight once it drifts above
    # base_weight × threshold (e.g. 1.4: a 5% target trimmed past 7%).
    # Checked at month starts between rebalances.
    band_trim_threshold: float | None = None
    # Replace a holding whose composite-score percentile (1.0 = best) falls
    # below this level with the best non-held name. Monthly check.
    replace_if_rank_below: float | None = None
    # Per-position exit vs volume-weighted entry price, checked daily on
    # close: stop_loss_pct (e.g. -0.10) and/or take_profit_pct (e.g. 0.30).
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None

    # --- Absolute-momentum gate (Phase 4.4 E4). OFF by default — every
    # existing strategy/backtest is unchanged when this stays False. ---
    # When true, after ranking, any top_n candidate whose own
    # ``abs_momentum_factor`` value is not strictly positive is dropped from
    # the selection. Dropped slots are left as cash (not redistributed to
    # the survivors) — see engine._allocate_equal_weight's fixed `slots`
    # divisor.
    abs_momentum_gate: bool = False
    abs_momentum_factor: str = "MOMENTUM_12M"
