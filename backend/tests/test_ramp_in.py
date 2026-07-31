"""라이브 분할 진입(ramp-in) — 경과 개월 캡 + 매수 예산 절삭."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.app.services.batch.proposal_generator import (
    ProposalDraft,
    apply_ramp_cap,
    ramp_cap,
)


def test_ramp_cap_progression():
    enabled = datetime(2026, 8, 1, 9, 0)
    assert ramp_cap(enabled, 4, now=datetime(2026, 8, 15)) == pytest.approx(0.25)
    assert ramp_cap(enabled, 4, now=datetime(2026, 9, 15)) == pytest.approx(0.50)
    assert ramp_cap(enabled, 4, now=datetime(2026, 11, 15)) == pytest.approx(1.0)
    assert ramp_cap(enabled, 4, now=datetime(2027, 3, 1)) == 1.0  # 초과분 클램프


def test_ramp_cap_disabled():
    assert ramp_cap(None, 6, now=datetime(2026, 8, 1)) == 1.0
    assert ramp_cap(datetime(2026, 8, 1), 0, now=datetime(2026, 8, 2)) == 1.0


def _buy(code: str, qty: int, price: float) -> ProposalDraft:
    return ProposalDraft(code, "BUY", qty, price, {"rule": "REBALANCE"})


def test_apply_ramp_cap_trims_buys_to_budget():
    drafts = [
        ProposalDraft("005930", "SELL", 2, 70_000.0, {"rule": "STOP_LOSS"}),
        _buy("069500", 10, 10_000.0),   # 100k
        _buy("133690", 10, 20_000.0),   # 200k
    ]
    # cap 0.25 × nav 1M = 250k 예산 − 보유 100k = 150k → 첫 BUY 100k 전체 +
    # 둘째 BUY는 50k/20k = 2주로 절삭
    out = apply_ramp_cap(
        drafts, cap=0.25, sleeve_nav=1_000_000.0, holdings_value=100_000.0
    )
    assert [(d.stock_code, d.side, d.qty) for d in out] == [
        ("005930", "SELL", 2),  # SELL 무변경
        ("069500", "BUY", 10),
        ("133690", "BUY", 2),
    ]


def test_apply_ramp_cap_full_cap_noop():
    drafts = [_buy("069500", 10, 10_000.0)]
    assert apply_ramp_cap(
        drafts, cap=1.0, sleeve_nav=1_000_000.0, holdings_value=0.0
    ) == drafts


def test_apply_ramp_cap_zero_budget_drops_buys():
    drafts = [_buy("069500", 10, 10_000.0),
              ProposalDraft("005930", "SELL", 1, 70_000.0, {"rule": "REBALANCE"})]
    out = apply_ramp_cap(
        drafts, cap=0.1, sleeve_nav=1_000_000.0, holdings_value=200_000.0
    )
    assert [(d.stock_code, d.side) for d in out] == [("005930", "SELL")]
