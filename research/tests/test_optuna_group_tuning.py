"""Optuna group-weight tuning support (grouped qlab_alpha_v2 strategies)."""

from __future__ import annotations

from datetime import date

import optuna
import pytest

from research.optimization.optuna_runner import _strategy_with_params, _suggest_strategy
from shared.domain.strategy import FactorGroup, GroupFactor, StrategyDefinition


def _grouped_strategy() -> StrategyDefinition:
    return StrategyDefinition(
        name="grouped",
        description="group tuning test",
        universe="KOSPI200",
        rebalance_freq="QUARTERLY",
        factors=[],
        filters=[],
        top_n=5,
        start_date=date(2020, 1, 1),
        end_date=date(2023, 12, 31),
        groups=[
            FactorGroup(name="Value", weight=0.5, factors=[GroupFactor(factor="PER", higher_is_better=False)]),
            FactorGroup(name="Flow", weight=0.5, factors=[GroupFactor(factor="FOREIGN_NET_20D")]),
        ],
    )


def test_suggest_strategy_tunes_group_weights():
    strategy = _grouped_strategy()
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=1))
    trial = study.ask()
    candidate = _suggest_strategy(strategy, trial, weight_low=-2.0, weight_high=2.0)
    assert candidate.groups is not None
    for group in candidate.groups:
        assert 0.05 <= group.weight <= 1.0
    assert set(trial.params) == {"group_value_weight", "group_flow_weight"}
    # Source strategy untouched.
    assert strategy.groups[0].weight == 0.5


def test_strategy_with_params_applies_group_weights():
    strategy = _grouped_strategy()
    tuned = _strategy_with_params(
        strategy, {"group_value_weight": 0.9, "group_flow_weight": 0.1}
    )
    weights = {g.name: g.weight for g in tuned.groups}
    assert weights == {"Value": pytest.approx(0.9), "Flow": pytest.approx(0.1)}


def test_flat_strategy_path_unchanged():
    from shared.domain.strategy import FactorWeight

    flat = _grouped_strategy().model_copy(
        update={
            "groups": None,
            "factors": [FactorWeight(factor="PER", weight=-1.0, transform="ZSCORE")],
        },
        deep=True,
    )
    tuned = _strategy_with_params(flat, {"per_weight": -0.5})
    assert tuned.factors[0].weight == pytest.approx(-0.5)
