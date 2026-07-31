"""미이행 리밸런스 이월 — 목표 저장·diff 빌더·잔여 노셔널."""
from __future__ import annotations

import pytest

from backend.app.services.batch.proposal_generator import (
    build_carryover_drafts,
    carryover_residual_notional,
)


def test_build_carryover_drafts_diff_and_order():
    target = {"069500": 10, "133690": 5}
    positions = {"069500": 4, "005930": 3}  # 005930은 목표 밖 → SELL
    prices = {"069500": 10_000.0, "133690": 20_000.0, "005930": 70_000.0}
    drafts = build_carryover_drafts(target, positions, prices)
    # SELL 먼저 정렬 (현금 확보) — full_rebalance_proposals와 동일 시맨틱
    assert [d.side for d in drafts] == ["SELL", "BUY", "BUY"]
    by_code = {d.stock_code: d for d in drafts}
    assert (by_code["005930"].side, by_code["005930"].qty) == ("SELL", 3)
    assert (by_code["069500"].side, by_code["069500"].qty) == ("BUY", 6)
    assert (by_code["133690"].side, by_code["133690"].qty) == ("BUY", 5)
    assert all(d.reason["rule"] == "REBALANCE_CARRYOVER" for d in drafts)


def test_build_carryover_drafts_skips_missing_price_and_zero_diff():
    target = {"069500": 10, "133690": 5}
    positions = {"069500": 10}
    prices = {"069500": 10_000.0}  # 133690 가격 없음 → 스킵
    assert build_carryover_drafts(target, positions, prices) == []


def test_carryover_residual_notional():
    target = {"069500": 10}
    positions = {"069500": 4}
    prices = {"069500": 10_000.0}
    assert carryover_residual_notional(target, positions, prices) == pytest.approx(
        60_000.0
    )
    assert carryover_residual_notional(target, {"069500": 10}, prices) == 0.0
