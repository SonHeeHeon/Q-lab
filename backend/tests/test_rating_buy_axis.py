"""매수축 등급 서비스(buy_axis) 단위 테스트 — DB-free, score_stocks/get_universe monkeypatch."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import backend.app.services.ratings.buy_axis as buy_axis
from backend.app.services.ratings.buy_axis import (
    EXTRAS_CAP,
    compute_buy_ratings,
    resolve_rating_strategy,
)
from shared.domain.strategy import StrategyDefinition

_AS_OF = "2026-01-02"


def _strategy(**overrides) -> StrategyDefinition:
    payload = dict(
        name="rating_test",
        description="rating tests",
        universe="KOSPI200",
        rebalance_freq="QUARTERLY",
        factors=[],
        filters=[],
        top_n=5,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
    )
    payload.update(overrides)
    return StrategyDefinition.model_validate(payload)


# 5개 유니버스 코드, 서로 다른 점수 → count(strictly-below)/5 가 정확히
# 0.8/0.6/0.4/0.2/0.0 quintile 경계를 만든다.
_UNIVERSE_5 = ["000001", "000002", "000003", "000004", "000005"]
_SCORES_5 = {"000001": 5.0, "000002": 4.0, "000003": 3.0, "000004": 2.0, "000005": 1.0}


def _score_frame(scores: dict[str, float], weakest_group: dict[str, str] | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(
        {"score": list(scores.values())}, index=pd.Index(list(scores.keys()), name="code")
    )
    if weakest_group is not None:
        frame["weakest_group"] = [weakest_group.get(code) for code in scores]
    return frame.sort_values("score", ascending=False)


@pytest.fixture()
def patch_universe(monkeypatch: pytest.MonkeyPatch):
    def _apply(universe_codes: list[str]):
        monkeypatch.setattr(
            buy_axis,
            "get_universe",
            lambda universe, *, as_of, db_path=None: list(universe_codes),
        )

    return _apply


@pytest.fixture()
def patch_scores(monkeypatch: pytest.MonkeyPatch):
    """score_stocks를 대체 — 호출 인자를 caller가 넘겨준 리스트에 기록한다."""

    def _apply(frame: pd.DataFrame, captured_calls: list | None = None):
        def fake_score_stocks(codes, factors, *, as_of, db_path=None, warnings=None,
                               groups=None, min_groups=5, winsor_pct=0.01, clip_z=3.0):
            if captured_calls is not None:
                captured_calls.append(list(codes))
            return frame

        monkeypatch.setattr(buy_axis, "score_stocks", fake_score_stocks)

    return _apply


def test_quintile_boundaries_exact(patch_universe, patch_scores):
    patch_universe(_UNIVERSE_5)
    patch_scores(_score_frame(_SCORES_5))

    result = compute_buy_ratings(_strategy(), as_of=_AS_OF)

    grades = {r.code: (r.percentile, r.buy_grade) for r in result.ratings}
    assert grades["000001"] == (pytest.approx(0.8), "STRONG_BUY")
    assert grades["000002"] == (pytest.approx(0.6), "BUY")
    assert grades["000003"] == (pytest.approx(0.4), "NEUTRAL")
    assert grades["000004"] == (pytest.approx(0.2), "REDUCE")
    assert grades["000005"] == (pytest.approx(0.0), "AVOID")
    assert result.universe_size == 5
    assert result.as_of == _AS_OF
    assert result.strategy_name == "rating_test"


def test_extras_excluded_from_reference_distribution(patch_universe, patch_scores):
    patch_universe(_UNIVERSE_5)
    scores_with_extra = dict(_SCORES_5)
    scores_with_extra["000099"] = 100.0  # extra: 유니버스보다 훨씬 높은 점수
    patch_scores(_score_frame(scores_with_extra))

    result = compute_buy_ratings(_strategy(), extra_codes=["000099"], as_of=_AS_OF)

    by_code = {r.code: r for r in result.ratings}
    # 유니버스 멤버 백분위는 extra 추가 전과 동일해야 한다 (기준 분포 불변).
    assert by_code["000001"].percentile == pytest.approx(0.8)
    assert by_code["000002"].percentile == pytest.approx(0.6)
    assert by_code["000003"].percentile == pytest.approx(0.4)
    assert by_code["000004"].percentile == pytest.approx(0.2)
    assert by_code["000005"].percentile == pytest.approx(0.0)
    # extra 자신은 유니버스 전원보다 높으므로 1.0 (5/5) → STRONG_BUY.
    extra = by_code["000099"]
    assert extra.status == "OK"
    assert extra.percentile == pytest.approx(1.0)
    assert extra.buy_grade == "STRONG_BUY"


def test_no_data_for_dropped_code(patch_universe, patch_scores):
    patch_universe(_UNIVERSE_5)
    dropped_scores = dict(_SCORES_5)
    del dropped_scores["000003"]  # score_stocks가 NaN 스코어 행을 드랍한 상황 시뮬레이션
    patch_scores(_score_frame(dropped_scores))

    result = compute_buy_ratings(_strategy(), as_of=_AS_OF)

    by_code = {r.code: r for r in result.ratings}
    dropped = by_code["000003"]
    assert dropped.status == "NO_DATA"
    assert dropped.buy_grade is None
    assert dropped.score is None
    assert dropped.percentile is None
    assert by_code["000001"].status == "OK"


def test_unsupported_ticker_never_reaches_score_stocks(patch_universe, patch_scores):
    patch_universe(_UNIVERSE_5)
    captured_calls: list = []
    patch_scores(_score_frame(_SCORES_5), captured_calls)

    result = compute_buy_ratings(_strategy(), extra_codes=["AAPL"], as_of=_AS_OF)

    by_code = {r.code: r for r in result.ratings}
    aapl = by_code["AAPL"]
    assert aapl.status == "UNSUPPORTED"
    assert aapl.buy_grade is None
    assert aapl.score is None
    # AAPL은 score_stocks 호출 인자에 절대 포함되지 않는다.
    assert "AAPL" not in captured_calls[0]


def test_extras_cap_warning_truncates_to_50(patch_universe, patch_scores):
    patch_universe([])
    many_extras = [f"{100000 + i}" for i in range(60)]
    captured_calls: list = []
    # Superset frame covering all 60 candidate codes; only the capped 50 that
    # actually get requested will be looked up.
    patch_scores(
        _score_frame({code: float(i) for i, code in enumerate(many_extras)}),
        captured_calls,
    )

    result = compute_buy_ratings(_strategy(), extra_codes=many_extras, as_of=_AS_OF)

    assert len(captured_calls[0]) == EXTRAS_CAP
    assert any("truncated to 50" in w and "60" in w for w in result.warnings)
    assert len(result.ratings) == EXTRAS_CAP


def test_flat_path_no_weakest_group_column(patch_universe, patch_scores):
    patch_universe(_UNIVERSE_5)
    patch_scores(_score_frame(_SCORES_5))  # no weakest_group column (flat path)

    result = compute_buy_ratings(_strategy(groups=None), as_of=_AS_OF)

    assert all(r.weakest_group is None for r in result.ratings)


def test_grouped_path_reports_weakest_group(patch_universe, patch_scores):
    patch_universe(_UNIVERSE_5)
    weakest = {code: "VALUE" for code in _UNIVERSE_5}
    weakest["000001"] = "QUALITY"
    patch_scores(_score_frame(_SCORES_5, weakest_group=weakest))

    result = compute_buy_ratings(_strategy(), as_of=_AS_OF)

    by_code = {r.code: r for r in result.ratings}
    assert by_code["000001"].weakest_group == "QUALITY"
    assert by_code["000002"].weakest_group == "VALUE"


def test_resolve_fallback_warning_when_name_missing(monkeypatch: pytest.MonkeyPatch):
    fallback_strategy = _strategy(name="value_v1")

    def fake_load_strategy(name: str) -> StrategyDefinition:
        if name == "value_v1":
            return fallback_strategy
        raise FileNotFoundError(f"Strategy file not found: {name}.yaml")

    monkeypatch.setattr(buy_axis, "load_strategy", fake_load_strategy)
    monkeypatch.setattr(buy_axis.settings, "DEFAULT_STRATEGY_NAME", "value_v1")

    strategy, warning = resolve_rating_strategy("does_not_exist")

    assert strategy is fallback_strategy
    assert warning is not None
    assert "does_not_exist" in warning
    assert "value_v1" in warning
