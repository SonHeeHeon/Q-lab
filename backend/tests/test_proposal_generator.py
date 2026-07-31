"""Proposal generator tests (Phase 4.2-B2): pure builders + insert/expiry."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

import backend.app.services.batch.proposal_generator as pg
from backend.app.schemas.portfolio import (
    PortfolioResponse,
    PortfolioSummary,
    PositionResponse,
)
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


def test_score_exit_swap_skips_when_replacement_price_missing():
    # 교체 종목(000003) 가격이 없으면 매도만 나가는 고아 매도를 막아야 한다
    # -> SELL/BUY 둘 다 생성되지 않음.
    drafts = build_rule_proposals(
        strategy=_strategy(replace_if_rank_below=0.4),
        positions={"000002": 50},
        entry_prices={"000002": 10000.0},
        prices={"000002": 10000.0},  # 000003 가격 없음
        nav=500_000,
        ranked_codes=["000003", "000001", "000002"],  # B가 최하위
    )
    assert drafts == []


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


def test_full_rebalance_slots_omitted_matches_explicit_none():
    """E5 배선: slots 생략 시 _allocate_equal_weight(slots=None)과 동일 —
    게이트 OFF일 때 기존 동작과 바이트 단위로 동일해야 한다."""
    kwargs = dict(
        positions={}, prices={"000001": 10000.0, "000002": 10000.0}, nav=100_000,
        selected=["000001", "000002"],
    )
    assert full_rebalance_proposals(**kwargs) == full_rebalance_proposals(
        **kwargs, slots=None
    )


def test_full_rebalance_slots_cash_pads_dropped_slot_instead_of_redistributing():
    """게이트로 selected에서 종목 하나가 빠졌을 때 slots(게이트 전 top_n)를 고정
    분모로 넘기면, 남은 생존자에게 재분배하지 않고 그 슬롯은 현금으로 남는다
    (engine._allocate_equal_weight와 동일 계약)."""
    prices = {"000001": 10000.0, "000003": 10000.0}
    drafts = full_rebalance_proposals(
        positions={}, prices=prices, nav=300_000,
        selected=["000001", "000003"], slots=3,  # 게이트 전 top_n=3
    )
    buys = {d.stock_code: d.qty for d in drafts if d.side == "BUY"}
    expected = pg._allocate_equal_weight(
        ["000001", "000003"], nav=300_000, prices=prices, exposure=1.0, slots=3,
    )
    assert buys == expected
    redistributed = pg._allocate_equal_weight(
        ["000001", "000003"], nav=300_000, prices=prices, exposure=1.0, slots=2,
    )
    assert buys != redistributed  # 고정 분모(3)가 실제로 적용됐는지 대조


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
    # 반환은 (건수, batch_id) — 같은 종목·방향 PROPOSED 중복 금지
    assert (first[0], second[0]) == (1, 0)
    assert first[1] is not None and second[1] is None

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


# --- _research_closes (가격 공백 보강) ---------------------------------------------

def _make_research_db(tmp_path, rows):
    """rows: (stock_code, date, close, adj_close) 튜플 목록으로 임시 research.db 생성."""
    db_path = tmp_path / "research.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE prices_daily "
            "(stock_code TEXT, date TEXT, close REAL, adj_close REAL)"
        )
        conn.executemany("INSERT INTO prices_daily VALUES (?, ?, ?, ?)", rows)
        conn.commit()
    return db_path


def test_research_closes_latest_price_up_to_as_of(tmp_path, monkeypatch):
    db_path = _make_research_db(
        tmp_path,
        [
            ("000001", "2026-07-10", 10000.0, None),
            ("000001", "2026-07-13", 10500.0, 10600.0),  # adj_close 우선
            ("000002", "2026-07-13", 5000.0, None),
            ("000002", "2026-07-14", 5200.0, None),  # as_of 이후 — 제외돼야 함
        ],
    )
    monkeypatch.setattr(pg, "research_db_path", db_path)

    closes = pg._research_closes(
        ["000001", "000002", "000003"], date(2026, 7, 13)
    )

    # 000003은 행이 아예 없음 -> 결과에서 조용히 빠짐(0.0으로 채우지 않음).
    assert closes == {"000001": 10600.0, "000002": 5000.0}


def test_research_closes_empty_codes_returns_empty_dict(tmp_path, monkeypatch):
    db_path = _make_research_db(tmp_path, [("000001", "2026-07-13", 100.0, None)])
    monkeypatch.setattr(pg, "research_db_path", db_path)
    assert pg._research_closes([], date(2026, 7, 13)) == {}


# --- run_proposal_generation 통합: 비보유 종목 가격 공백 보강 ----------------------

class _FakeKISClient:
    """단일 잔고를 반환하는 페이크 KIS 클라이언트(test_rating_batch.py 스타일)."""

    def __init__(self, portfolio: PortfolioResponse):
        self._portfolio = portfolio

    async def get_balance(self, account_type):
        del account_type
        return self._portfolio


class _FakeScored:
    """score_stocks/apply_filters 스텁이 돌려주는, .index만 노출하는 가짜 결과."""

    def __init__(self, codes):
        self.index = codes


async def test_full_rebalance_backfills_research_price_for_new_buy(
    tmp_path, monkeypatch, service_sessionmaker
):
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)

    as_of = date(2026, 7, 13)
    monkeypatch.setattr(pg, "latest_research_price_date", lambda: as_of)

    # 000002(비보유)는 브로커 잔고엔 없고, 연구DB에만 종가가 있음.
    db_path = _make_research_db(tmp_path, [("000002", "2026-07-13", 12000.0, None)])
    monkeypatch.setattr(pg, "research_db_path", db_path)

    strategy = _strategy(top_n=2)
    monkeypatch.setattr(pg, "load_strategy", lambda name: strategy)

    ranked = ["000001", "000002", "000003"]
    # get_universe는 이제 슬리브 분리를 위해 "ETF_KR"로도 별도 호출된다 — 이
    # 전략은 KOSPI200이므로 ETF 유니버스는 비어 있고(주식 슬리브에 전부 남음),
    # 전략 자신의 유니버스 호출에만 ranked를 돌려준다.
    monkeypatch.setattr(
        pg, "get_universe",
        lambda universe, *a, **k: [] if universe == "ETF_KR" else ranked,
    )
    monkeypatch.setattr(pg, "score_stocks", lambda *a, **k: _FakeScored(ranked))
    monkeypatch.setattr(pg, "apply_filters", lambda scored, *a, **k: scored)

    portfolio = PortfolioResponse(
        positions=[
            PositionResponse(
                stock_code="000001", quantity=10,
                avg_buy_price=Decimal("9000"), current_price=Decimal("9500"),
            )
        ],
        summary=PortfolioSummary(total_evaluation_amount=Decimal("1000000")),
    )
    monkeypatch.setattr(pg, "KISRestClient", lambda: _FakeKISClient(portfolio))

    summary = await pg.run_proposal_generation(
        account_type=pg.AccountType.PAPER, full_rebalance=True, send_telegram=False,
    )
    assert summary["drafted"] >= 1

    async with service_sessionmaker() as session:
        rows = (await session.execute(pg.select(OrderProposal))).scalars().all()
    buys_000002 = [r for r in rows if r.stock_code == "000002" and r.side == "BUY"]
    assert len(buys_000002) == 1  # 백필된 연구 종가로 비보유 종목 BUY가 살아남음
    assert float(buys_000002[0].last_price) == pytest.approx(12000.0)


# --- 절대모멘텀 게이트 (E5): 백테스트 엔진 로직을 라이브에 그대로 재사용 -----------

async def test_full_rebalance_abs_momentum_gate_invokes_engine_helper_and_cash_pads(
    tmp_path, monkeypatch, service_sessionmaker
):
    """게이트 ON이면 (1) 엔진의 _apply_abs_momentum_gate가 실제로 호출되고
    (게이트 전 top_n 선택 전체 + 올바른 factor_name으로), (2) 자기 모멘텀<=0인
    종목(000002)은 매수되지 않으며, (3) 배분 분모(slots)는 게이트 전 top_n(3)으로
    고정돼 생존자에게 재분배되지 않고 그 슬롯은 현금으로 남는다."""
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    as_of = date(2026, 7, 13)
    monkeypatch.setattr(pg, "latest_research_price_date", lambda: as_of)

    ranked = ["000001", "000002", "000003"]
    prices = {"000001": 10000.0, "000002": 10000.0, "000003": 10000.0}
    db_path = _make_research_db(
        tmp_path, [(code, "2026-07-13", px, None) for code, px in prices.items()],
    )
    monkeypatch.setattr(pg, "research_db_path", db_path)

    strategy = _strategy(
        name="stock_gate", universe="CUSTOM", top_n=3, abs_momentum_gate=True,
    )
    monkeypatch.setattr(pg, "load_strategy", lambda name: strategy)

    # 실제 pandas 프레임 — 엔진 헬퍼가 재구현이 아니라 이 프레임의 컬럼값을
    # 그대로 읽는지 확인하기 위함 (000002만 모멘텀<=0).
    scored = pd.DataFrame(
        {"MOMENTUM_12M": [0.10, -0.05, 0.20]}, index=pd.Index(ranked, name="code"),
    )
    monkeypatch.setattr(
        pg, "get_universe",
        lambda universe, *a, **k: [] if universe == "ETF_KR" else ranked,
    )
    monkeypatch.setattr(pg, "score_stocks", lambda *a, **k: scored)
    monkeypatch.setattr(pg, "apply_filters", lambda scored, *a, **k: scored)

    calls: list[tuple[list[str], str]] = []
    real_gate = pg._apply_abs_momentum_gate

    def _spy_gate(selected, scored_frame, *, factor_name, **kwargs):
        calls.append((list(selected), factor_name))
        assert scored_frame is scored  # 진짜 스코어 프레임을 그대로 받는지
        return real_gate(selected, scored_frame, factor_name=factor_name, **kwargs)

    monkeypatch.setattr(pg, "_apply_abs_momentum_gate", _spy_gate)

    portfolio = _portfolio(nav="10000000")  # 무보유 — 신규 진입

    await pg.run_proposal_generation(
        strategy_name="stock_gate", account_type=pg.AccountType.PAPER,
        full_rebalance=True, send_telegram=False,
        nav_weight=1.0, prefetched_balance=portfolio,
    )

    assert calls == [(["000001", "000002", "000003"], "MOMENTUM_12M")]

    async with service_sessionmaker() as session:
        rows = (await session.execute(pg.select(OrderProposal))).scalars().all()
    buys = {r.stock_code: r.qty for r in rows if r.side == "BUY"}

    assert "000002" not in buys  # 모멘텀<=0 -> 게이트 탈락, 매수 없음
    expected = pg._allocate_equal_weight(
        ["000001", "000003"], nav=10_000_000, prices=prices, exposure=1.0, slots=3,
    )
    assert buys == expected


async def test_full_rebalance_gate_off_never_calls_engine_gate_helper(
    tmp_path, monkeypatch, service_sessionmaker
):
    """게이트 OFF(기본값)면 _apply_abs_momentum_gate 자체가 호출되지 않는다 —
    slots도 항상 None으로 넘어가 오늘 동작과 바이트 단위로 동일하다."""
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    as_of = date(2026, 7, 13)
    monkeypatch.setattr(pg, "latest_research_price_date", lambda: as_of)

    ranked = ["000001", "000002"]
    prices = {"000001": 10000.0, "000002": 10000.0}
    db_path = _make_research_db(
        tmp_path, [(code, "2026-07-13", px, None) for code, px in prices.items()],
    )
    monkeypatch.setattr(pg, "research_db_path", db_path)

    strategy = _strategy(name="stock_no_gate", universe="CUSTOM", top_n=2)
    assert strategy.abs_momentum_gate is False
    monkeypatch.setattr(pg, "load_strategy", lambda name: strategy)

    monkeypatch.setattr(
        pg, "get_universe",
        lambda universe, *a, **k: [] if universe == "ETF_KR" else ranked,
    )
    monkeypatch.setattr(pg, "score_stocks", lambda *a, **k: _FakeScored(ranked))
    monkeypatch.setattr(pg, "apply_filters", lambda scored, *a, **k: scored)

    called: list[int] = []
    monkeypatch.setattr(
        pg, "_apply_abs_momentum_gate",
        lambda selected, *a, **k: (called.append(1), selected)[1],
    )

    portfolio = _portfolio(nav="1000000")

    await pg.run_proposal_generation(
        strategy_name="stock_no_gate", account_type=pg.AccountType.PAPER,
        full_rebalance=True, send_telegram=False,
        nav_weight=1.0, prefetched_balance=portfolio,
    )

    assert called == []


# --- 슬리브 스코핑 (T4/T5): ETF/주식 슬리브 안전장치 ------------------------------

def _portfolio(*positions: PositionResponse, nav: str) -> PortfolioResponse:
    return PortfolioResponse(
        positions=list(positions),
        summary=PortfolioSummary(total_evaluation_amount=Decimal(nav)),
    )


async def test_etf_sleeve_full_rebalance_never_sells_stock_code(
    monkeypatch, service_sessionmaker
):
    """등급T4/T5 헤드라인 1: ETF 슬리브 full_rebalance는 보유 주식 코드를
    보지도 못한다 — 파티션 단계에서 애초에 걸러진다."""
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    as_of = date(2026, 7, 13)
    monkeypatch.setattr(pg, "latest_research_price_date", lambda: as_of)

    etf_strategy = _strategy(name="etf_sleeve", universe="ETF_KR", top_n=1)
    monkeypatch.setattr(pg, "load_strategy", lambda name: etf_strategy)

    etf_codes = ["069500"]
    monkeypatch.setattr(pg, "get_universe", lambda *a, **k: etf_codes)
    monkeypatch.setattr(pg, "score_stocks", lambda *a, **k: _FakeScored(etf_codes))
    monkeypatch.setattr(pg, "apply_filters", lambda scored, *a, **k: scored)

    portfolio = _portfolio(
        PositionResponse(
            stock_code="069500", quantity=10,
            avg_buy_price=Decimal("10000"), current_price=Decimal("10000"),
        ),
        PositionResponse(
            stock_code="000001", quantity=50,  # 주식 코드 — ETF 슬리브가 절대 못 봄
            avg_buy_price=Decimal("5000"), current_price=Decimal("2500"),  # -50%
        ),
        nav="10000000",
    )

    await pg.run_proposal_generation(
        strategy_name="etf_sleeve", account_type=pg.AccountType.PAPER,
        full_rebalance=True, send_telegram=False,
        nav_weight=0.3, prefetched_balance=portfolio,
    )

    async with service_sessionmaker() as session:
        rows = (await session.execute(pg.select(OrderProposal))).scalars().all()
    sell_codes = {r.stock_code for r in rows if r.side == "SELL"}
    assert "000001" not in sell_codes


async def test_stock_sleeve_rules_never_sells_etf_code(
    monkeypatch, service_sessionmaker
):
    """헤드라인 2: 손절 규칙이 켜진 주식 슬리브는 -50%로 폭락한 ETF 보유를
    절대 매도하지 않는다 — ETF는 파티션 단계에서 이미 제외됨."""
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    as_of = date(2026, 7, 13)
    monkeypatch.setattr(pg, "latest_research_price_date", lambda: as_of)

    stock_strategy = _strategy(
        name="stock_sleeve", universe="CUSTOM", stop_loss_pct=-0.10,
    )
    monkeypatch.setattr(pg, "load_strategy", lambda name: stock_strategy)

    etf_codes = ["069500"]
    monkeypatch.setattr(pg, "get_universe", lambda *a, **k: etf_codes)

    portfolio = _portfolio(
        PositionResponse(
            stock_code="069500", quantity=10,
            avg_buy_price=Decimal("10000"), current_price=Decimal("5000"),  # -50%
        ),
        PositionResponse(
            stock_code="000001", quantity=50,
            avg_buy_price=Decimal("10000"), current_price=Decimal("9500"),  # -5%
        ),
        nav="1000000",
    )

    await pg.run_proposal_generation(
        strategy_name="stock_sleeve", account_type=pg.AccountType.PAPER,
        full_rebalance=False, send_telegram=False,
        nav_weight=0.7, prefetched_balance=portfolio,
    )

    async with service_sessionmaker() as session:
        rows = (await session.execute(pg.select(OrderProposal))).scalars().all()
    sell_codes = {r.stock_code for r in rows if r.side == "SELL"}
    assert "069500" not in sell_codes


async def test_sleeve_nav_math_etf_target_sized_off_weighted_nav(
    tmp_path, monkeypatch, service_sessionmaker
):
    """헤드라인 3: nav=10_000_000, w=0.3 → ETF 슬리브 예산은 3_000_000이고,
    목표 수량은 그 예산 기준으로 계산된다(계좌 전체 NAV 기준이 아님)."""
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    as_of = date(2026, 7, 13)
    monkeypatch.setattr(pg, "latest_research_price_date", lambda: as_of)

    db_path = _make_research_db(tmp_path, [("069500", "2026-07-13", 10000.0, None)])
    monkeypatch.setattr(pg, "research_db_path", db_path)

    etf_strategy = _strategy(name="etf_sleeve", universe="ETF_KR", top_n=1)
    monkeypatch.setattr(pg, "load_strategy", lambda name: etf_strategy)

    etf_codes = ["069500"]
    monkeypatch.setattr(pg, "get_universe", lambda *a, **k: etf_codes)
    monkeypatch.setattr(pg, "score_stocks", lambda *a, **k: _FakeScored(etf_codes))
    monkeypatch.setattr(pg, "apply_filters", lambda scored, *a, **k: scored)

    portfolio = _portfolio(nav="10000000")  # 무보유 — 신규 진입

    await pg.run_proposal_generation(
        strategy_name="etf_sleeve", account_type=pg.AccountType.PAPER,
        full_rebalance=True, send_telegram=False,
        nav_weight=0.3, prefetched_balance=portfolio,
    )

    async with service_sessionmaker() as session:
        rows = (await session.execute(pg.select(OrderProposal))).scalars().all()
    buy = next(r for r in rows if r.stock_code == "069500" and r.side == "BUY")
    # sleeve_nav = 10_000_000 * 0.3 = 3_000_000; _allocate_equal_weight는 현금
    # 버퍼로 engine.INVESTABLE_NAV_RATIO(0.995)를 곱한다.
    assert buy.qty == int((3_000_000 * 0.995) // 10000.0)


def test_is_month_start_true_when_prev_trading_day_in_prior_month(
    tmp_path, monkeypatch
):
    db_path = _make_research_db(
        tmp_path,
        [
            ("000001", "2026-06-30", 100.0, None),
            ("000001", "2026-07-01", 101.0, None),
        ],
    )
    monkeypatch.setattr(pg, "research_db_path", db_path)
    assert pg._is_month_start(date(2026, 7, 1)) is True


def test_is_month_start_false_when_prev_trading_day_same_month(
    tmp_path, monkeypatch
):
    db_path = _make_research_db(
        tmp_path,
        [
            ("000001", "2026-07-10", 100.0, None),
            ("000001", "2026-07-13", 101.0, None),
        ],
    )
    monkeypatch.setattr(pg, "research_db_path", db_path)
    assert pg._is_month_start(date(2026, 7, 13)) is False


async def test_insert_dedup_is_scoped_per_strategy(service_sessionmaker, monkeypatch):
    """헤드라인 5: 전략 A의 PROPOSED 행이 전략 B의 같은 종목/방향 제안을
    막지 않는다."""
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    strategy_a = _strategy(name="strat_a")
    strategy_b = _strategy(name="strat_b")
    drafts = [ProposalDraft("000001", "SELL", 10, 1000.0, {"rule": "BAND_TRIM"})]

    first = await pg._insert_proposals(
        drafts, strategy=strategy_a, account=pg.AccountType.PAPER,
        as_of=date(2026, 7, 13),
    )
    second = await pg._insert_proposals(
        drafts, strategy=strategy_b, account=pg.AccountType.PAPER,
        as_of=date(2026, 7, 13),
    )
    assert (first[0], second[0]) == (1, 1)  # (건수, batch_id) 반환

    async with service_sessionmaker() as session:
        rows = (await session.execute(pg.select(OrderProposal))).scalars().all()
    assert {r.strategy_name for r in rows} == {"strat_a", "strat_b"}


class _CountingFakeKISClient:
    calls = 0

    def __init__(self, portfolio: PortfolioResponse):
        self._portfolio = portfolio

    async def get_balance(self, account_type):
        del account_type
        type(self).calls += 1
        return self._portfolio


async def test_orchestrator_single_balance_fetch_and_sleeve_isolation(
    monkeypatch, service_sessionmaker
):
    """헤드라인 6: run_sleeve_proposals는 잔고를 딱 1번만 조회해 두 슬리브에
    재사용하고, 한쪽 슬리브 예외(전략 파일 누락)가 다른 쪽을 막지 않는다."""
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    as_of = date(2026, 7, 13)
    monkeypatch.setattr(pg, "latest_research_price_date", lambda: as_of)
    monkeypatch.setattr(pg, "_is_month_start", lambda _as_of: True)
    monkeypatch.setattr(pg, "get_universe", lambda *a, **k: [])

    def _load_strategy(name):
        if name == "missing_etf_strategy":
            raise FileNotFoundError(f"Strategy file not found: {name}.yaml")
        return _strategy(name=name, universe="CUSTOM", stop_loss_pct=-0.10)

    monkeypatch.setattr(pg, "load_strategy", _load_strategy)

    portfolio = _portfolio(
        PositionResponse(
            stock_code="000001", quantity=10,
            avg_buy_price=Decimal("10000"), current_price=Decimal("8000"),  # -20%
        ),
        nav="1000000",
    )
    _CountingFakeKISClient.calls = 0
    monkeypatch.setattr(pg, "KISRestClient", lambda: _CountingFakeKISClient(portfolio))

    async with service_sessionmaker() as session:
        session.add(pg.Setting(key="rating_strategy_name", value="stock_strategy"))
        session.add(pg.Setting(key="etf_strategy_name", value="missing_etf_strategy"))
        session.add(pg.Setting(key="sleeve_etf_weight", value="0.3"))
        await session.commit()

    summary = await pg.run_sleeve_proposals(send_telegram=False)

    assert _CountingFakeKISClient.calls == 1
    assert "error" in summary["sleeves"]["etf"]
    assert summary["sleeves"]["stock"].get("drafted", 0) >= 1


async def test_orchestrator_etf_sleeve_skipped_when_not_month_start(
    monkeypatch, service_sessionmaker
):
    """오케스트레이터 비월초 분기: ETF 슬리브는 이월(carryover) 경로로 가고,
    이번 주기 저장 목표가 없으면 'no saved target this period'로 스킵한다
    (주식 슬리브는 정상 실행). 2026-07-31 이월 기능으로 시맨틱 갱신."""
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    as_of = date(2026, 7, 13)
    monkeypatch.setattr(pg, "latest_research_price_date", lambda: as_of)
    monkeypatch.setattr(pg, "_is_month_start", lambda _as_of: False)
    monkeypatch.setattr(pg, "get_universe", lambda *a, **k: [])
    monkeypatch.setattr(
        pg, "load_strategy",
        lambda name: _strategy(name=name, universe="CUSTOM", stop_loss_pct=-0.10),
    )

    portfolio = _portfolio(
        PositionResponse(
            stock_code="000001", quantity=10,
            avg_buy_price=Decimal("10000"), current_price=Decimal("8000"),
        ),
        nav="1000000",
    )
    _CountingFakeKISClient.calls = 0
    monkeypatch.setattr(pg, "KISRestClient", lambda: _CountingFakeKISClient(portfolio))

    summary = await pg.run_sleeve_proposals(send_telegram=False)

    assert summary["sleeves"]["etf"] == {"skipped": "no saved target this period"}
    assert summary["sleeves"]["stock"].get("drafted", 0) >= 1
    assert _CountingFakeKISClient.calls == 1


# --- SELL 초안 세금 주석 (T7) -----------------------------------------------------

async def test_sell_tax_annotated_for_stock_code_and_buy_carries_none(
    tmp_path, monkeypatch, service_sessionmaker
):
    """주식 슬리브 SCORE_EXIT: 매도(000002)는 거래세 추정치가 붙고, 같은
    배치의 매수(000003)는 세금 키를 전혀 갖지 않는다."""
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    as_of = date(2026, 7, 13)
    monkeypatch.setattr(pg, "latest_research_price_date", lambda: as_of)

    # 000003(비보유 교체 종목)의 연구 종가만 있으면 됨.
    db_path = _make_research_db(tmp_path, [("000003", "2026-07-13", 20000.0, None)])
    monkeypatch.setattr(pg, "research_db_path", db_path)

    stock_strategy = _strategy(
        name="stock_sleeve", universe="CUSTOM", replace_if_rank_below=0.5,
    )
    monkeypatch.setattr(pg, "load_strategy", lambda name: stock_strategy)

    ranked = ["000003", "000001", "000002"]  # 000002가 최하위 -> 교체 대상
    monkeypatch.setattr(
        pg, "get_universe",
        lambda universe, *a, **k: [] if universe == "ETF_KR" else ranked,
    )
    monkeypatch.setattr(pg, "score_stocks", lambda *a, **k: _FakeScored(ranked))
    monkeypatch.setattr(pg, "apply_filters", lambda scored, *a, **k: scored)

    portfolio = _portfolio(
        PositionResponse(
            stock_code="000002", quantity=50,
            avg_buy_price=Decimal("10000"), current_price=Decimal("10000"),
        ),
        nav="1000000",
    )

    await pg.run_proposal_generation(
        strategy_name="stock_sleeve", account_type=pg.AccountType.PAPER,
        full_rebalance=False, send_telegram=False,
        nav_weight=1.0, prefetched_balance=portfolio,
    )

    async with service_sessionmaker() as session:
        rows = (await session.execute(pg.select(OrderProposal))).scalars().all()

    sell = next(r for r in rows if r.stock_code == "000002" and r.side == "SELL")
    reason = json.loads(sell.reason_json)
    assert reason["tax_type"] == "stock"
    assert reason["est_sell_tax"] == round(50 * 10000 * 0.0015)  # 750
    assert reason["est_gains_tax"] == 0
    assert reason["tax_note"]

    buy = next(r for r in rows if r.stock_code == "000003" and r.side == "BUY")
    buy_reason = json.loads(buy.reason_json)
    assert "tax_type" not in buy_reason
    assert "est_sell_tax" not in buy_reason
    assert "est_gains_tax" not in buy_reason


async def test_sell_tax_annotated_for_taxable_etf_with_gain(
    tmp_path, monkeypatch, service_sessionmaker
):
    """ETF 슬리브 full_rebalance: 과세대상 ETF(114800, KODEX 인버스) 매도는
    매매차익 배당소득세 15.4%가 추정치로 붙는다 (kr_etf_tax_class.csv 실데이터
    기준 분류 — is_etf 플래그가 아니라 CSV의 taxable 분류가 우선한다)."""
    monkeypatch.setattr(pg, "service_session", service_sessionmaker)
    as_of = date(2026, 7, 13)
    monkeypatch.setattr(pg, "latest_research_price_date", lambda: as_of)

    # 091160(목표 편입 대상)의 연구 종가만 보강하면 됨 — 114800은 보유 중이라
    # 잔고 조회에서 이미 가격을 받는다.
    db_path = _make_research_db(tmp_path, [("091160", "2026-07-13", 30000.0, None)])
    monkeypatch.setattr(pg, "research_db_path", db_path)

    etf_strategy = _strategy(name="etf_sleeve", universe="ETF_KR", top_n=1)
    monkeypatch.setattr(pg, "load_strategy", lambda name: etf_strategy)

    etf_codes = ["091160", "114800"]  # 091160 선택(top_n=1) / 114800 탈락 -> 매도
    monkeypatch.setattr(pg, "get_universe", lambda *a, **k: etf_codes)
    monkeypatch.setattr(pg, "score_stocks", lambda *a, **k: _FakeScored(etf_codes))
    monkeypatch.setattr(pg, "apply_filters", lambda scored, *a, **k: scored)

    portfolio = _portfolio(
        PositionResponse(
            stock_code="114800", quantity=10,
            avg_buy_price=Decimal("10000"), current_price=Decimal("15000"),  # +50%
        ),
        nav="10000000",
    )

    await pg.run_proposal_generation(
        strategy_name="etf_sleeve", account_type=pg.AccountType.PAPER,
        full_rebalance=True, send_telegram=False,
        nav_weight=0.3, prefetched_balance=portfolio,
    )

    async with service_sessionmaker() as session:
        rows = (await session.execute(pg.select(OrderProposal))).scalars().all()

    sell = next(r for r in rows if r.stock_code == "114800" and r.side == "SELL")
    reason = json.loads(sell.reason_json)
    assert reason["tax_type"] == "etf_taxable"
    assert reason["est_sell_tax"] == 0
    assert reason["est_gains_tax"] == round(0.154 * (15000 - 10000) * 10)  # 7700
    assert reason["tax_note"]
