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


class StrategyDefinition(BaseModel):
    """Parameterized value equation, serializable to and from YAML."""

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
