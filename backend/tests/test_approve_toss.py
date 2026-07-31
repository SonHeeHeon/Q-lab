"""US(market='US') 제안 승인은 Toss 클라이언트로 라우팅된다."""
from __future__ import annotations

from datetime import date

from backend.app.api.proposals import _order_request_for
from shared.db.models import OrderProposal
from shared.domain.account import AccountType, BrokerType


def _proposal(market: str, code: str) -> OrderProposal:
    return OrderProposal(
        batch_id="b1", proposal_date=date(2026, 7, 31),
        account_type="REAL", strategy_name="s", stock_code=code, market=market,
        side="BUY", qty=1, order_type="LIMIT", limit_price=100, last_price=100,
    )


def test_us_proposal_routes_to_toss():
    req = _order_request_for(_proposal("US", "AAPL"), client_order_id="c1")
    assert req.broker is BrokerType.TOSS
    assert req.stock_code == "AAPL"  # zfill 오염 금지
    assert req.client_order_id == "c1"


def test_kr_proposal_routes_to_kis():
    req = _order_request_for(_proposal("KR", "69500"), client_order_id="c2")
    assert req.broker is BrokerType.KIS
    assert req.account_type is AccountType.REAL
    assert req.stock_code == "069500"  # KR은 기존 zfill 유지


def test_missing_market_defaults_to_kis():
    proposal = _proposal("KR", "005930")
    proposal.market = None
    req = _order_request_for(proposal, client_order_id="c3")
    assert req.broker is BrokerType.KIS
