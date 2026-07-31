"""통합 포트폴리오 — exclude_paper 시 모의(PAPER) 계좌 제외."""
from __future__ import annotations

from backend.app.api.portfolio import _unified_account_types
from shared.domain.account import AccountType


def test_default_includes_all_accounts():
    assert _unified_account_types(exclude_paper=False) == list(AccountType)


def test_exclude_paper_drops_only_paper():
    types = _unified_account_types(exclude_paper=True)
    assert AccountType.PAPER not in types
    assert types == [t for t in AccountType if t is not AccountType.PAPER]
