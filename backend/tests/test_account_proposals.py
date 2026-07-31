"""N계좌 오케스트레이터 순수 로직: hold 슬리브 diff + DC 노출 가드."""
from __future__ import annotations

from backend.app.services.batch.account_proposals import (
    _dc_exposure_warning,
    hold_sleeve_proposals,
)


def test_hold_sleeve_buys_up_to_target():
    drafts = hold_sleeve_proposals(
        code="153130", weight=0.32, nav=10_000_000,
        positions={}, prices={"153130": 100_000.0},
    )
    assert len(drafts) == 1
    d = drafts[0]
    assert (d.side, d.qty) == ("BUY", 32)  # 3.2M / 100k
    assert d.reason["rule"] == "REBALANCE"
    assert d.reason["hold"] is True


def test_hold_sleeve_sells_excess():
    drafts = hold_sleeve_proposals(
        code="153130", weight=0.32, nav=10_000_000,
        positions={"153130": 50}, prices={"153130": 100_000.0},
    )
    assert [(d.side, d.qty) for d in drafts] == [("SELL", 18)]


def test_hold_sleeve_within_band_no_trade():
    drafts = hold_sleeve_proposals(
        code="153130", weight=0.32, nav=10_000_000,
        positions={"153130": 32}, prices={"153130": 100_000.0},
    )
    assert drafts == []


def test_hold_sleeve_no_price_no_trade():
    """순수 함수 계약: 가격이 정말 없으면 무거래. 최초 매수의 가격 공백은
    호출부(_run_hold_sleeve)가 연구 종가 폴백으로 채운다 (리뷰 P1-4)."""
    assert hold_sleeve_proposals(
        code="153130", weight=0.32, nav=10_000_000, positions={}, prices={},
    ) == []


def test_dc_exposure_warning_over_70pct():
    warning = _dc_exposure_warning(
        risky_value=7_500_000, nav=10_000_000, profile_type="DC",
    )
    assert warning and "70%" in warning


def test_dc_exposure_warning_ok_under_70pct():
    assert _dc_exposure_warning(
        risky_value=6_500_000, nav=10_000_000, profile_type="IRP",
    ) is None


def test_dc_exposure_warning_none_for_personal():
    assert _dc_exposure_warning(
        risky_value=9_000_000, nav=10_000_000, profile_type="PERSONAL",
    ) is None
