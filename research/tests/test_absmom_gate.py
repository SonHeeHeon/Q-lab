"""E4 absolute-momentum gate + E3 leverage/inverse guardrail (engine.py).

Gate: off by default — must reproduce the pre-change allocation math
exactly (nav*ratio*exposure / len(selected)). When on, candidates with a
non-positive abs_momentum_factor value are dropped from the selection, but
the allocation divisor stays fixed at the pre-gate slot count so the
dropped slots become cash instead of being redistributed to survivors.

Guardrail: ETF_KR excludes leverage/inverse-named ETFs (e.g. 114800 KODEX
인버스) while keeping legitimate hedged/futures ETFs (e.g. "...선물(H)").
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

from research.backtest.engine import (
    INVESTABLE_NAV_RATIO,
    _allocate_equal_weight,
    _apply_abs_momentum_gate,
    get_universe,
)
from shared.domain.strategy import StrategyDefinition

AS_OF = date(2026, 6, 30)
NAV = 100_000_000.0
PRICES = {"A": 10_000.0, "B": 10_000.0, "C": 10_000.0}


# ---------------------------------------------------------------------------
# Gate OFF (default) — allocation regression
# ---------------------------------------------------------------------------


def test_allocate_default_matches_len_divisor_path():
    """No `slots` passed (today's every existing call site when the gate is
    off) must match the old `len(selected_codes)` divisor math exactly."""
    selected = ["A", "B", "C"]
    default = _allocate_equal_weight(selected, nav=NAV, prices=PRICES, exposure=1.0)
    explicit = _allocate_equal_weight(
        selected, nav=NAV, prices=PRICES, exposure=1.0, slots=len(selected)
    )
    assert default == explicit
    expected_budget = NAV * INVESTABLE_NAV_RATIO * 1.0 / len(selected)
    assert default["A"] == int(expected_budget // PRICES["A"])


def test_gate_off_selection_unaffected_by_helper():
    """`_apply_abs_momentum_gate` is only invoked by run_backtest when the
    strategy flag is on — the default StrategyDefinition never calls it, so
    the pre-gate `selected` list flows to `_execute` untouched."""
    strategy = StrategyDefinition(
        name="off",
        description="off",
        universe="ETF_KR",
        rebalance_freq="MONTHLY",
        factors=[],
        filters=[],
        top_n=3,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 1),
    )
    assert strategy.abs_momentum_gate is False


# ---------------------------------------------------------------------------
# Gate ON — drop negative-momentum names, cash-pad the dropped slots
# ---------------------------------------------------------------------------


def _scored_frame(values: dict[str, float]) -> pd.DataFrame:
    frame = pd.DataFrame(index=pd.Index(list(values), name="code"))
    frame["MOMENTUM_12M"] = pd.Series(values)
    frame["score"] = frame["MOMENTUM_12M"]
    return frame.sort_values("score", ascending=False)


def test_gate_on_drops_negative_momentum_and_cash_pads():
    scored = _scored_frame({"A": 0.10, "B": 0.05, "C": -0.02})
    selected = list(scored.head(3).index)
    slots = len(selected)  # fixed divisor taken BEFORE the gate drops anyone
    assert slots == 3

    gated = _apply_abs_momentum_gate(
        selected,
        scored,
        factor_name="MOMENTUM_12M",
        as_of=AS_OF,
        db_path=None,
        warnings=None,
    )
    assert gated == ["A", "B"]

    target = _allocate_equal_weight(
        gated, nav=NAV, prices=PRICES, exposure=1.0, slots=slots
    )
    expected_budget = NAV * INVESTABLE_NAV_RATIO * 1.0 / 3  # nav/3, NOT nav/2
    assert target["A"] == int(expected_budget // PRICES["A"])
    assert target["B"] == int(expected_budget // PRICES["B"])
    assert "C" not in target
    # Sanity: nav/3 sizing must differ from the naive nav/len(gated)=nav/2 sizing.
    wrong_budget = NAV * INVESTABLE_NAV_RATIO * 1.0 / len(gated)
    assert int(expected_budget // PRICES["A"]) != int(wrong_budget // PRICES["A"])


def test_gate_on_all_negative_holds_all_cash():
    scored = _scored_frame({"A": -0.01, "B": -0.02, "C": -0.03})
    selected = list(scored.head(3).index)
    slots = len(selected)

    gated = _apply_abs_momentum_gate(
        selected,
        scored,
        factor_name="MOMENTUM_12M",
        as_of=AS_OF,
        db_path=None,
        warnings=None,
    )
    assert gated == []

    target = _allocate_equal_weight(
        gated, nav=NAV, prices=PRICES, exposure=1.0, slots=slots
    )
    assert target == {}  # no positions → all cash


def test_gate_on_missing_factor_value_is_dropped():
    """A selected code absent from the scored frame's factor column can't
    confirm positive momentum — treated as failing the gate."""
    scored = _scored_frame({"A": 0.10, "B": 0.05})
    scored.loc["C"] = {"MOMENTUM_12M": float("nan"), "score": float("nan")}
    gated = _apply_abs_momentum_gate(
        ["A", "B", "C"],
        scored,
        factor_name="MOMENTUM_12M",
        as_of=AS_OF,
        db_path=None,
        warnings=None,
    )
    assert gated == ["A", "B"]


# ---------------------------------------------------------------------------
# StrategyDefinition — defaults + YAML round-trip
# ---------------------------------------------------------------------------


def test_strategy_definition_abs_momentum_gate_defaults_off():
    strategy = StrategyDefinition(
        name="s",
        description="s",
        universe="ETF_KR",
        rebalance_freq="MONTHLY",
        factors=[],
        filters=[],
        top_n=3,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 1),
    )
    assert strategy.abs_momentum_gate is False
    assert strategy.abs_momentum_factor == "MOMENTUM_12M"


def test_strategy_definition_loads_abs_momentum_gate_from_yaml():
    payload = {
        "name": "s",
        "description": "s",
        "universe": "ETF_KR",
        "rebalance_freq": "MONTHLY",
        "factors": [],
        "filters": [],
        "top_n": 3,
        "start_date": "2020-01-01",
        "end_date": "2020-02-01",
        "abs_momentum_gate": True,
        "abs_momentum_factor": "MOMENTUM_3M",
    }
    strategy = StrategyDefinition.model_validate(payload)
    assert strategy.abs_momentum_gate is True
    assert strategy.abs_momentum_factor == "MOMENTUM_3M"


def test_etf_rotation_kr_yaml_validates_with_liquidity_filter_and_gate_off():
    # 2026-07-27: 공개 yaml은 기본판(게이트 OFF) — OOS로 채택된 게이트 ON 튜닝판은
    # research/strategies/private/(gitignore) 전용이고, 로더가 private을 우선한다.
    path = Path("research/strategies/etf_rotation_kr.yaml")
    with path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file)
    strategy = StrategyDefinition.model_validate(payload)
    assert strategy.abs_momentum_gate is False  # 공개 기본판은 OFF
    assert strategy.abs_momentum_factor == "MOMENTUM_12M"
    assert len(strategy.filters) == 1
    liquidity = strategy.filters[0]
    assert liquidity.field == "TURNOVER_PROXY"
    assert liquidity.op == "GTE"
    assert liquidity.value == 100_000_000


# ---------------------------------------------------------------------------
# E3 — leverage/inverse exclusion in get_universe("ETF_KR")
# ---------------------------------------------------------------------------


@pytest.fixture()
def leverage_db(tmp_path: Path) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE stocks (code TEXT PRIMARY KEY, name TEXT, market TEXT,"
            " sector TEXT, industry TEXT, listed_at TEXT, delisted_at TEXT,"
            " is_delisted INTEGER DEFAULT 0)"
        )
        conn.executemany(
            "INSERT INTO stocks (code,name,market,listed_at,delisted_at) VALUES (?,?,?,?,?)",
            [
                ("069500", "KODEX 200", "ETF", "2002-10-14", None),
                ("114800", "KODEX 인버스", "ETF", "2009-09-16", None),  # excluded
                ("999001", "KODEX 코스닥150레버리지", "ETF", "2015-01-01", None),  # excluded
                # Hedged futures ETF — legitimate single-exposure product,
                # must NOT be caught by the leverage/inverse markers.
                ("143850", "TIGER 미국S&P500선물(H)", "ETF", "2016-01-01", None),
            ],
        )
    return path


def test_get_universe_excludes_leverage_and_inverse_etfs(leverage_db: Path) -> None:
    codes = get_universe("ETF_KR", as_of=AS_OF, db_path=leverage_db)
    assert codes == ["069500", "143850"]
    assert "114800" not in codes
    assert "999001" not in codes
