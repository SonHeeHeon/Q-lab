"""매도축 등급 규칙 엔진 테스트 (Phase T3): 순수 함수, DB/브로커 없음."""

from __future__ import annotations

from datetime import date

import pytest

from backend.app.services.ratings.sell_axis import PositionContext, rate_position
from shared.domain.strategy import StrategyDefinition


def _strategy(**overrides) -> StrategyDefinition:
    payload = dict(
        name="rating_test",
        description="sell axis rating tests",
        universe="KOSPI200",
        rebalance_freq="QUARTERLY",
        factors=[],
        filters=[],
        top_n=2,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    payload.update(overrides)
    return StrategyDefinition.model_validate(payload)


def _ctx(**overrides) -> PositionContext:
    payload = dict(
        code="000001",
        pl_rate=None,
        percentile=None,
        weakest_group=None,
        position_value=None,
        nav=None,
        holding_count=None,
        in_universe=True,
        is_us=False,
    )
    payload.update(overrides)
    return PositionContext(**payload)


STOP_LOSS_PCT = -10.0


# --- Tier 1: STOP_LOSS -----------------------------------------------------

def test_stop_loss_exact_boundary_triggers_sell_now():
    grade, reason = rate_position(
        _ctx(pl_rate=-10.0), _strategy(), stop_loss_pct=STOP_LOSS_PCT
    )
    assert grade == "SELL_NOW"
    assert reason == {"rule": "STOP_LOSS", "pl_rate": -10.0, "threshold": -10.0}


def test_stop_loss_just_above_threshold_falls_through():
    grade, reason = rate_position(
        _ctx(pl_rate=-9.99, percentile=0.5), _strategy(), stop_loss_pct=STOP_LOSS_PCT
    )
    assert grade == "HOLD"
    assert reason["rule"] == "SCORE_PERCENTILE"


def test_stop_loss_beats_no_data():
    # percentile 없음(NO_DATA 대상)이어도 STOP_LOSS가 먼저 발동해야 한다.
    grade, reason = rate_position(
        _ctx(pl_rate=-15.0, percentile=None), _strategy(), stop_loss_pct=STOP_LOSS_PCT
    )
    assert grade == "SELL_NOW"
    assert reason["rule"] == "STOP_LOSS"


# --- Tier 2: TAKE_PROFIT ----------------------------------------------------

def test_take_profit_inert_when_none():
    # take_profit_pct 미설정 시 아무리 수익이 커도 TAKE_PROFIT은 발동하지 않는다.
    grade, reason = rate_position(
        _ctx(pl_rate=100.0, percentile=0.8),
        _strategy(take_profit_pct=None),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "KEEP"
    assert reason["rule"] == "SCORE_PERCENTILE"


def test_take_profit_active_with_unit_normalization():
    # strategy.take_profit_pct는 분수(0.5=+50%), pl_rate는 %(55.0=+55%).
    # 0.5 * 100 = 50.0 <= 55.0 이므로 발동해야 한다.
    grade, reason = rate_position(
        _ctx(pl_rate=55.0, percentile=0.8),
        _strategy(take_profit_pct=0.5),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "SELL"
    assert reason == {"rule": "TAKE_PROFIT", "pl_rate": 55.0, "threshold": 50.0}


def test_take_profit_just_below_threshold_falls_through():
    grade, reason = rate_position(
        _ctx(pl_rate=49.9, percentile=0.8),
        _strategy(take_profit_pct=0.5),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "KEEP"
    assert reason["rule"] == "SCORE_PERCENTILE"


# --- Tier 3/5: SCORE_PERCENTILE --------------------------------------------

@pytest.mark.parametrize(
    "percentile,expected_grade",
    [
        (0.0, "SELL"),
        (0.1999, "SELL"),
        (0.2, "WATCH"),  # 경계: 0.2<=p<0.4
        (0.3999, "WATCH"),
        (0.4, "HOLD"),  # 경계: 0.4<=p<0.6
        (0.5999, "HOLD"),
        (0.6, "KEEP"),  # 경계: p>=0.6
        (1.0, "KEEP"),
    ],
)
def test_percentile_boundaries(percentile, expected_grade):
    grade, reason = rate_position(
        _ctx(percentile=percentile), _strategy(), stop_loss_pct=STOP_LOSS_PCT
    )
    assert grade == expected_grade
    assert reason["rule"] == "SCORE_PERCENTILE"
    assert reason["percentile"] == percentile


def test_percentile_reason_includes_weakest_group_when_present():
    grade, reason = rate_position(
        _ctx(percentile=0.1, weakest_group="VALUE"),
        _strategy(),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "SELL"
    assert reason["weakest_group"] == "VALUE"


def test_percentile_reason_omits_weakest_group_when_absent():
    grade, reason = rate_position(
        _ctx(percentile=0.1, weakest_group=None), _strategy(), stop_loss_pct=STOP_LOSS_PCT
    )
    assert "weakest_group" not in reason


# --- Tier 4: BAND_TRIM (CAP) -------------------------------------------------

def test_band_trim_caps_keep_to_watch_when_over_target():
    # holding_count=5 -> base_weight = 0.995/5 = 0.199; threshold=1.2 ->
    # ceiling = 0.2388. weight = 250_000/1_000_000 = 0.25 > ceiling.
    grade, reason = rate_position(
        _ctx(
            percentile=0.9,  # 원래는 KEEP
            position_value=250_000.0,
            nav=1_000_000.0,
            holding_count=5,
            in_universe=True,
        ),
        _strategy(band_trim_threshold=1.2),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "WATCH"
    assert reason["rule"] == "BAND_TRIM"
    assert reason["weight"] == pytest.approx(0.25)
    assert reason["target"] == pytest.approx(0.199)


def test_band_trim_caps_hold_to_watch_when_over_target():
    grade, reason = rate_position(
        _ctx(
            percentile=0.5,  # 원래는 HOLD
            position_value=250_000.0,
            nav=1_000_000.0,
            holding_count=5,
            in_universe=True,
        ),
        _strategy(band_trim_threshold=1.2),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "WATCH"
    assert reason["rule"] == "BAND_TRIM"


def test_band_trim_does_not_fire_within_band():
    grade, reason = rate_position(
        _ctx(
            percentile=0.9,
            position_value=200_000.0,  # weight=0.2 < ceiling 0.2388
            nav=1_000_000.0,
            holding_count=5,
            in_universe=True,
        ),
        _strategy(band_trim_threshold=1.2),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "KEEP"
    assert reason["rule"] == "SCORE_PERCENTILE"


def test_band_trim_never_upgrades_sell():
    # percentile<0.2 이미 SELL — band-trim이 SELL을 더 나쁘게(승격) 만들지 않는다.
    grade, reason = rate_position(
        _ctx(
            percentile=0.1,
            position_value=250_000.0,
            nav=1_000_000.0,
            holding_count=5,
            in_universe=True,
        ),
        _strategy(band_trim_threshold=1.2),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "SELL"
    assert reason["rule"] == "SCORE_PERCENTILE"


def test_band_trim_never_changes_watch():
    # percentile 0.2<=p<0.4 이미 WATCH — 이미 하한이므로 변화 없음.
    grade, reason = rate_position(
        _ctx(
            percentile=0.3,
            position_value=250_000.0,
            nav=1_000_000.0,
            holding_count=5,
            in_universe=True,
        ),
        _strategy(band_trim_threshold=1.2),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "WATCH"
    assert reason["rule"] == "SCORE_PERCENTILE"


def test_band_trim_skipped_when_threshold_not_set():
    grade, reason = rate_position(
        _ctx(
            percentile=0.9,
            position_value=250_000.0,
            nav=1_000_000.0,
            holding_count=5,
            in_universe=True,
        ),
        _strategy(band_trim_threshold=None),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "KEEP"
    assert reason["rule"] == "SCORE_PERCENTILE"


def test_band_trim_skipped_when_not_in_universe():
    grade, reason = rate_position(
        _ctx(
            percentile=0.9,
            position_value=250_000.0,
            nav=1_000_000.0,
            holding_count=5,
            in_universe=False,
        ),
        _strategy(band_trim_threshold=1.2),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "KEEP"
    assert reason["rule"] == "SCORE_PERCENTILE"


def test_band_trim_skipped_when_required_values_missing():
    grade, reason = rate_position(
        _ctx(
            percentile=0.9,
            position_value=None,
            nav=1_000_000.0,
            holding_count=5,
            in_universe=True,
        ),
        _strategy(band_trim_threshold=1.2),
        stop_loss_pct=STOP_LOSS_PCT,
    )
    assert grade == "KEEP"
    assert reason["rule"] == "SCORE_PERCENTILE"


# --- Tier 6: NO_DATA ---------------------------------------------------------

def test_no_data_kr_holds_without_us_note():
    grade, reason = rate_position(
        _ctx(percentile=None, is_us=False), _strategy(), stop_loss_pct=STOP_LOSS_PCT
    )
    assert grade == "HOLD"
    assert reason == {"rule": "NO_DATA"}


def test_no_data_us_holds_with_us_note():
    grade, reason = rate_position(
        _ctx(percentile=None, is_us=True), _strategy(), stop_loss_pct=STOP_LOSS_PCT
    )
    assert grade == "HOLD"
    assert reason == {"rule": "NO_DATA", "note": "US"}


# --- General: reason never empty --------------------------------------------

@pytest.mark.parametrize(
    "ctx_kwargs,strategy_kwargs",
    [
        ({"pl_rate": -20.0}, {}),
        ({"percentile": 0.1}, {}),
        ({"percentile": 0.5}, {}),
        ({"percentile": None}, {}),
        ({"percentile": None, "is_us": True}, {}),
    ],
)
def test_reason_always_non_empty_and_has_rule(ctx_kwargs, strategy_kwargs):
    grade, reason = rate_position(
        _ctx(**ctx_kwargs), _strategy(**strategy_kwargs), stop_loss_pct=STOP_LOSS_PCT
    )
    assert reason
    assert "rule" in reason
