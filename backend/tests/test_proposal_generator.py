"""Proposal generator tests (Phase 4.2-B2): pure builders + insert/expiry."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

import backend.app.services.batch.proposal_generator as pg
from backend.app.services.batch.proposal_generator import (
    ProposalDraft,
    build_rule_proposals,
    full_rebalance_proposals,
)
from shared.db.models import OrderProposal
from shared.domain.strategy import StrategyDefinition


def _strategy(**overrides) -> StrategyDefinition:
    payload = dict(
        name="prop_test",
        description="proposal tests",
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


# --- build_rule_proposals -------------------------------------------------------

def test_stop_loss_full_exit_proposal():
    drafts = build_rule_proposals(
        strategy=_strategy(stop_loss_pct=-0.10),
        positions={"000001": 100},
        entry_prices={"000001": 10000.0},
        prices={"000001": 8800.0},  # -12%
        nav=1_000_000,
    )
    assert len(drafts) == 1
    d = drafts[0]
    assert (d.side, d.qty, d.reason["rule"]) == ("SELL", 100, "STOP_LOSS")
    assert d.limit_price == pytest.approx(8800.0 * 1.003, rel=1e-6)


def test_take_profit_and_band_trim_do_not_double_sell():
    # 급등 종목이 익절 대상이면 밴드트림은 그 종목을 건드리지 않는다.
    drafts = build_rule_proposals(
        strategy=_strategy(take_profit_pct=0.30, band_trim_threshold=1.3),
        positions={"000001": 100, "000002": 100},
        entry_prices={"000001": 10000.0, "000002": 10000.0},
        prices={"000001": 14000.0, "000002": 10000.0},  # A +40%
        nav=2_400_000,
    )
    sells_a = [d for d in drafts if d.stock_code == "000001"]
    assert len(sells_a) == 1
    assert sells_a[0].reason["rule"] == "TAKE_PROFIT"
    assert sells_a[0].qty == 100  # 전량, 트림 중복 없음


def test_score_exit_swap_generates_sell_and_buy():
    drafts = build_rule_proposals(
        strategy=_strategy(replace_if_rank_below=0.4),
        positions={"000002": 50},
        entry_prices={"000002": 10000.0},
        prices={"000002": 10000.0, "000003": 20000.0},
        nav=500_000,
        ranked_codes=["000003", "000001", "000002"],  # B가 최하위
    )
    assert [(d.side, d.stock_code) for d in drafts] == [
        ("SELL", "000002"), ("BUY", "000003"),
    ]
    buy = drafts[1]
    assert buy.qty == int(50 * 10000 * 0.99 // 20000)  # 헤어컷 반영
    assert buy.reason["replaces"] == "000002"


def test_regime_derisk_scales_down():
    drafts = build_rule_proposals(
        strategy=_strategy(use_regime=True),
        positions={"000001": 100},
        entry_prices={"000001": 10000.0},
        prices={"000001": 10000.0},
        nav=1_000_000,
        invested_exposure=1.0,
        confirmed_regime_exposure=0.4,
    )
    assert len(drafts) == 1
    assert drafts[0].qty == 60  # 100 → 40 유지
    assert drafts[0].reason["rule"] == "REGIME_DERISK"


def test_no_rules_enabled_no_drafts():
    drafts = build_rule_proposals(
        strategy=_strategy(),
        positions={"000001": 100},
        entry_prices={"000001": 10000.0},
        prices={"000001": 5000.0},  # -50%지만 규칙 전부 off
        nav=500_000,
    )
    assert drafts == []


def test_full_rebalance_sells_before_buys():
    drafts = full_rebalance_proposals(
        positions={"000001": 100},                     # 탈락 종목
        prices={"000001": 100.0, "000002": 100.0, "000003": 100.0},
        nav=100_000,
        selected=["000002", "000003"],
    )
    assert drafts[0].side == "SELL" and drafts[0].stock_code == "000001"
    assert {d.stock_code for d in drafts if d.side == "BUY"} == {"000002", "000003"}
    assert all(d.reason["rule"] == "REBALANCE" for d in drafts)


# --- insert dedup + expiry (in-memory service DB) --------------------------------

async def test_insert_skips_duplicate_pending(service_sessionmaker, monkeypatch):
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    strategy = _strategy()
    drafts = [ProposalDraft("000001", "SELL", 10, 1000.0, {"rule": "BAND_TRIM"})]

    first = await pg._insert_proposals(
        drafts, strategy=strategy, account=pg.AccountType.PAPER, as_of=date(2026, 7, 13)
    )
    second = await pg._insert_proposals(
        drafts, strategy=strategy, account=pg.AccountType.PAPER, as_of=date(2026, 7, 13)
    )
    assert (first, second) == (1, 0)  # 같은 종목·방향 PROPOSED 중복 금지

    async with service_sessionmaker() as session:
        row = (await session.execute(pg.select(OrderProposal))).scalars().one()
        assert row.status == "PROPOSED"
        assert json.loads(row.reason_json)["rule"] == "BAND_TRIM"
        assert row.expires_at is not None and row.expires_at.hour == 8


async def test_expiry_marks_overdue(service_sessionmaker, monkeypatch):
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    async with service_sessionmaker() as session:
        session.add(OrderProposal(
            batch_id="b1", proposal_date=date(2026, 7, 10),
            strategy_name="s", stock_code="000001", side="BUY", qty=1,
            status="PROPOSED",
            expires_at=datetime.now() - timedelta(hours=1),
        ))
        session.add(OrderProposal(
            batch_id="b1", proposal_date=date(2026, 7, 13),
            strategy_name="s", stock_code="000002", side="BUY", qty=1,
            status="PROPOSED",
            expires_at=datetime.now() + timedelta(days=1),
        ))
        await session.commit()

    expired = await pg.run_proposal_expiry()
    assert expired == 1
    async with service_sessionmaker() as session:
        statuses = {
            row.stock_code: row.status
            for row in (await session.execute(pg.select(OrderProposal))).scalars()
        }
    assert statuses == {"000001": "EXPIRED", "000002": "PROPOSED"}


def test_next_business_morning_skips_weekend():
    # 금요일 기준 → 월요일 08:30
    assert pg._next_business_morning(date(2026, 7, 10)) == datetime(2026, 7, 13, 8, 30)
