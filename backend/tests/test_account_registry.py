"""6계좌 레지스트리 + 연금계좌 주문 차단."""
from __future__ import annotations

import pytest

from backend.app.core.config import settings
from shared.domain.account import AccountType


def test_account_type_has_six_members():
    assert [t.value for t in AccountType] == [
        "PAPER", "REAL", "ISA", "DC", "IRP", "PENSION",
    ]  # 검증 순서 보존: 기존 3 앞, 신규 3 뒤


def test_kis_account_resolves_all_types():
    for t in AccountType:
        acct = settings.kis_account(t)
        assert acct.type is t
        # 앱키 없으면 미연결(is_active=False)로 자연 처리 — 예외 금지
        assert isinstance(acct.is_active, bool)


def test_endpoints_resolve_for_all_types():
    from backend.app.services.kis.accounts import PAPER_ENDPOINTS, endpoints_for

    for t in AccountType:
        endpoints = endpoints_for(t)
        assert (endpoints is PAPER_ENDPOINTS) == (t is AccountType.PAPER)


def test_pension_order_blocked():
    from backend.app.schemas.portfolio import OrderRequest
    from backend.app.services.orders.guard import OrderBlocked, guard_order

    for t in (AccountType.DC, AccountType.IRP, AccountType.PENSION):
        req = OrderRequest(
            account_type=t, stock_code="069500", direction="BUY",
            quantity=1, order_type="MARKET",
        )
        with pytest.raises(OrderBlocked):
            guard_order(req, reference_price=10000.0)
