"""등급 배치 러너 테스트 (Phase T4, 2-슬리브 T10): EOD/인트라데이, 임시 service.db 사용.

compute_buy_ratings/resolve_rating_strategy는 합성 결과로 monkeypatch하고,
KIS 브로커는 계좌별 콜백을 주는 페이크로 대체한다. 실제 data/service.db는
절대 건드리지 않는다 — 전부 in-memory SQLite(``service_sessionmaker``)로 돈다.
``get_universe``/``latest_research_price_date``(ETF_KR 유니버스 유도)도
실제 research.db를 절대 건드리지 않도록 항상 monkeypatch한다.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

import backend.app.services.batch.rating_batch as rating_batch
from backend.app.services.ratings import store
from backend.app.services.ratings.buy_axis import BuyRating, BuyRatingsResult
from backend.app.schemas.portfolio import (
    PortfolioResponse,
    PortfolioSummary,
    PositionResponse,
)
from shared.db.models import PositionRating, Setting, StockRating
from shared.domain.account import AccountType, BrokerType
from shared.domain.strategy import StrategyDefinition


ETF_STRATEGY_NAME = "etf_rotation_kr"  # == settings.DEFAULT_ETF_STRATEGY_NAME


def _strategy(**overrides) -> StrategyDefinition:
    payload = dict(
        name="rating_batch_test",
        description="rating batch tests",
        universe="KOSPI200",
        rebalance_freq="QUARTERLY",
        factors=[],
        filters=[],
        top_n=5,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    payload.update(overrides)
    return StrategyDefinition.model_validate(payload)


def _etf_strategy(**overrides) -> StrategyDefinition:
    payload = dict(
        name=ETF_STRATEGY_NAME,
        description="etf sleeve tests",
        universe="ETF_KR",
        rebalance_freq="MONTHLY",
        factors=[],
        filters=[],
        top_n=3,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    payload.update(overrides)
    return StrategyDefinition.model_validate(payload)


def _default_resolve_rating_strategy(name):
    """주식/ETF 슬리브를 이름으로 구분해 반환하는 기본 fake (개별 테스트에서 override 가능)."""
    if name == ETF_STRATEGY_NAME:
        return _etf_strategy(), None
    return _strategy(), None


def _position(
    code: str,
    *,
    qty: int = 10,
    avg_buy_price: float = 10_000.0,
    current_price: float | None = None,
    evaluation_amount: float | None = None,
    unrealized_pl_rate: float | None = None,
) -> PositionResponse:
    return PositionResponse(
        stock_code=code,
        quantity=qty,
        avg_buy_price=Decimal(str(avg_buy_price)),
        current_price=Decimal(str(current_price)) if current_price is not None else None,
        evaluation_amount=(
            Decimal(str(evaluation_amount)) if evaluation_amount is not None else None
        ),
        unrealized_pl_rate=(
            Decimal(str(unrealized_pl_rate)) if unrealized_pl_rate is not None else None
        ),
    )


def _portfolio(
    positions: list[PositionResponse], *, nav: float = 1_000_000.0
) -> PortfolioResponse:
    return PortfolioResponse(
        positions=positions,
        summary=PortfolioSummary(total_evaluation_amount=Decimal(str(nav))),
    )


class _FakeKISClient:
    """계좌별 (PortfolioResponse | Exception)을 돌려주는 페이크 KIS 클라이언트."""

    def __init__(self, balances: dict[AccountType, object]):
        self._balances = {
            account_type: balances.get(account_type, _portfolio([], nav=0.0))
            for account_type in AccountType
        }

    async def get_balance(self, account_type: AccountType) -> PortfolioResponse:
        outcome = self._balances[account_type]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeTossClient:
    """항상 미설정 상태의 페이크 Toss 클라이언트 — 실제 네트워크 호출을 막는다.

    이 dev 환경의 .env에는 실제 Toss 자격증명이 들어 있을 수 있어, 실제
    TossRestClient를 그대로 두면 테스트가 실계좌 API를 호출한다. rating_batch
    가 Toss 분기를 스킵하도록 강제로 is_configured=False를 반환한다.
    """

    @classmethod
    def from_settings_map(cls, rows: dict) -> "_FakeTossClient":
        del rows
        return cls()

    @property
    def is_configured(self) -> bool:
        return False


DEFAULT_ETF_CODES = ["069500", "091160"]


def _fake_compute_buy_ratings(strategy, extra_codes=(), *, as_of=None, db_path=None):
    del extra_codes, as_of, db_path  # 합성 결과라 입력은 참고하지 않는다(기본 fake).
    if strategy.universe == "ETF_KR":
        ratings = [
            BuyRating(
                code=code, status="OK", buy_grade="NEUTRAL",
                score=1.0 - idx * 0.1, percentile=0.5, weakest_group=None,
            )
            for idx, code in enumerate(DEFAULT_ETF_CODES)
        ]
        return BuyRatingsResult(
            as_of="2026-07-24",
            strategy_name=strategy.name,
            universe_size=len(ratings),
            ratings=ratings,
            warnings=[],
        )
    universe_ratings = [
        BuyRating(
            code="000001", status="OK", buy_grade="STRONG_BUY",
            score=1.0, percentile=0.9, weakest_group=None,
        ),
        BuyRating(
            code="000002", status="OK", buy_grade="AVOID",
            score=0.1, percentile=0.1, weakest_group="VALUE",
        ),
    ]
    extra_ratings = [
        BuyRating(
            code="005930", status="OK", buy_grade="NEUTRAL",
            score=0.5, percentile=0.5, weakest_group=None,
        ),
    ]
    return BuyRatingsResult(
        as_of="2026-07-24",
        strategy_name=strategy.name,
        universe_size=len(universe_ratings),
        ratings=universe_ratings + extra_ratings,
        warnings=[],
    )


@pytest.fixture(autouse=True)
def _patch_common(monkeypatch, service_sessionmaker):
    # store.py와 rating_batch.py는 각자 shared.db.session.service_session을
    # 모듈 스코프로 import했으므로 둘 다 in-memory 테스트 DB로 갈아끼운다.
    monkeypatch.setattr(store, "service_session", service_sessionmaker)
    monkeypatch.setattr(rating_batch, "service_session", service_sessionmaker)
    monkeypatch.setattr(rating_batch, "compute_buy_ratings", _fake_compute_buy_ratings)
    monkeypatch.setattr(
        rating_batch, "resolve_rating_strategy", _default_resolve_rating_strategy
    )
    monkeypatch.setattr(rating_batch, "TossRestClient", _FakeTossClient)
    # get_universe/latest_research_price_date는 실제 research.db(sqlite3 직결)를
    # 건드리므로 항상 monkeypatch한다 — ETF_KR 유니버스는 기본적으로
    # DEFAULT_ETF_CODES를 반환한다(개별 테스트에서 override 가능).
    monkeypatch.setattr(
        rating_batch, "latest_research_price_date", lambda: date(2026, 7, 24)
    )
    monkeypatch.setattr(
        rating_batch,
        "get_universe",
        lambda universe, as_of=None, db_path=None: list(DEFAULT_ETF_CODES),
    )
    return service_sessionmaker


def _install_kis(monkeypatch, balances: dict[AccountType, object]) -> None:
    monkeypatch.setattr(rating_batch, "KISRestClient", lambda: _FakeKISClient(balances))


# --- EOD: stock + position upserts -----------------------------------------------

async def test_eod_upserts_stock_and_position_ratings(monkeypatch):
    _install_kis(
        monkeypatch,
        {
            AccountType.PAPER: _portfolio(
                [_position("000001", unrealized_pl_rate=10.0)], nav=500_000.0
            ),
            AccountType.REAL: _portfolio(
                [_position("005930", unrealized_pl_rate=-15.0)], nav=500_000.0
            ),
        },
    )

    summary = await rating_batch.run_rating_eod()

    # stock: universe(2) + extra(1) = 3, etf: DEFAULT_ETF_CODES(2) = 2 -> 합계 5.
    assert summary["stock_ratings_stored"] == 5
    assert summary["position_ratings_stored"] == 2
    assert summary["error_count"] == 0

    stock_rows = await store.get_stock_ratings(["000001", "000002", "005930"])
    assert {row["code"] for row in stock_rows} == {"000001", "000002", "005930"}

    position_rows = {row["code"]: row for row in await store.get_position_ratings()}
    # 000001: percentile 0.9 >= 0.6 -> KEEP (STOP_LOSS 미도달)
    assert position_rows["000001"]["sell_grade"] == "KEEP"
    assert position_rows["000001"]["reason"]["rule"] == "SCORE_PERCENTILE"
    # 005930: pl_rate -15 <= -10 스탑로스 -> SELL_NOW (percentile 무관)
    assert position_rows["005930"]["sell_grade"] == "SELL_NOW"
    assert position_rows["005930"]["reason"]["rule"] == "STOP_LOSS"

    latest = await store.latest_runs()
    assert latest["EOD"]["stored_count"] == 5
    assert latest["EOD"]["error_count"] == 0


# --- EOD: scoped delete preserves failed-account rows ----------------------------

async def test_eod_scoped_delete_preserves_failed_account_rows(monkeypatch):
    # ISA는 잔고 조회가 실패한다 -> 이 계좌의 기존 평가는 삭제 대상에서 빠져야 한다.
    _install_kis(
        monkeypatch,
        {
            AccountType.PAPER: _portfolio([], nav=0.0),
            AccountType.REAL: _portfolio([], nav=0.0),
            AccountType.ISA: RuntimeError("balance fetch failed"),
        },
    )

    async with rating_batch.service_session() as session:
        session.add(
            PositionRating(
                broker=BrokerType.KIS.value,
                account_key=AccountType.ISA.value,
                code="999999",
                sell_grade="HOLD",
                reason_json='{"rule": "NO_DATA"}',
                lane="EOD",
            )
        )
        await session.commit()

    summary = await rating_batch.run_rating_eod()

    assert summary["error_count"] == 1
    assert "ISA" not in summary["accounts_ok"]

    position_rows = {row["code"]: row for row in await store.get_position_ratings()}
    assert position_rows["999999"]["account_key"] == "ISA"
    assert position_rows["999999"]["sell_grade"] == "HOLD"  # 보존됨, 삭제되지 않음


# --- T10 (a) HEADLINE: ETF 슬리브가 주식 패스로 인해 클로버링되지 않음 -----------

async def test_eod_etf_sleeve_does_not_clobber_existing_etf_rating(monkeypatch):
    # 사전 시딩: 069500 행이 ETF 전략명으로 이미 저장돼 있다(예: 이전 배치·on-demand).
    async with rating_batch.service_session() as session:
        session.add(
            StockRating(
                code="069500",
                status="OK",
                buy_grade="BUY",
                score=0.8,
                percentile=0.9,
                weakest_group=None,
                strategy_name=ETF_STRATEGY_NAME,
                as_of=date(2026, 7, 20),
                updated_at=datetime(2026, 7, 20, 19, 0, 0),
            )
        )
        await session.commit()

    # 브로커는 주식 1종목 + ETF 1종목을 보유한다 — 069500(ETF)이 held_codes에
    # 들어가 stock extras 후보가 되므로, 차감 로직이 없으면 클로버링된다.
    _install_kis(
        monkeypatch,
        {
            AccountType.PAPER: _portfolio(
                [_position("000001", unrealized_pl_rate=5.0)], nav=500_000.0
            ),
            AccountType.REAL: _portfolio(
                [_position("069500", unrealized_pl_rate=3.0)], nav=500_000.0
            ),
        },
    )

    etf_codes = ["069500"]
    monkeypatch.setattr(
        rating_batch,
        "get_universe",
        lambda universe, as_of=None, db_path=None: list(etf_codes),
    )

    def _fake_compute(strategy, extra_codes=(), *, as_of=None, db_path=None):
        extra_list = list(extra_codes)
        if strategy.universe == "ETF_KR":
            assert extra_list == [], "ETF sleeve pass must not receive extras"
            ratings = [
                BuyRating(
                    code="069500", status="OK", buy_grade="STRONG_BUY",
                    score=1.0, percentile=1.0, weakest_group=None,
                ),
            ]
            return BuyRatingsResult(
                as_of="2026-07-24", strategy_name=strategy.name,
                universe_size=len(ratings), ratings=ratings, warnings=[],
            )
        # 클로버링 회귀 방어: ETF 코드가 주식 패스 extras로 새면 여기서 즉시 실패한다.
        assert "069500" not in extra_list, (
            "stock pass must not receive ETF codes as extras (clobbering bug)"
        )
        ratings = [
            BuyRating(
                code="000001", status="OK", buy_grade="STRONG_BUY",
                score=1.0, percentile=0.9, weakest_group=None,
            ),
        ]
        return BuyRatingsResult(
            as_of="2026-07-24", strategy_name=strategy.name,
            universe_size=len(ratings), ratings=ratings, warnings=[],
        )

    monkeypatch.setattr(rating_batch, "compute_buy_ratings", _fake_compute)

    await rating_batch.run_rating_eod()

    stock_rows = {
        row["code"]: row for row in await store.get_stock_ratings(["000001", "069500"])
    }
    # 069500은 NO_DATA로 덮어써지지 않고 ETF 전략명을 그대로(또는 재채점 후에도) 유지한다.
    assert stock_rows["069500"]["strategy_name"] == ETF_STRATEGY_NAME
    assert stock_rows["069500"]["status"] == "OK"
    assert stock_rows["069500"]["buy_grade"] == "STRONG_BUY"  # rank1 remap
    assert stock_rows["000001"]["strategy_name"] == "rating_batch_test"


# --- T10 (b) rank remap: 순위 기반 등급/백분위 -----------------------------------

def test_remap_etf_grades_rank_based_grades_and_percentile():
    ratings = [
        BuyRating(
            code=f"E{i}", status="OK", buy_grade=None,
            score=10.0 - i, percentile=None, weakest_group=None,
        )
        for i in range(10)
    ]
    result = BuyRatingsResult(
        as_of="2026-07-24", strategy_name=ETF_STRATEGY_NAME,
        universe_size=10, ratings=ratings, warnings=[],
    )

    remapped = rating_batch.remap_etf_grades(result, top_n=3)

    grades = {r.code: r.buy_grade for r in remapped.ratings}
    percentiles = {r.code: r.percentile for r in remapped.ratings}

    assert grades["E0"] == "STRONG_BUY"  # rank1 (최고 score)
    assert grades["E1"] == "BUY"         # rank2
    assert grades["E2"] == "BUY"         # rank3
    assert grades["E3"] == "NEUTRAL"     # rank4
    assert grades["E4"] == "NEUTRAL"     # rank5
    assert grades["E5"] == "AVOID"       # rank6
    assert grades["E9"] == "AVOID"       # rank10

    assert percentiles["E0"] == 1.0
    assert percentiles["E9"] == pytest.approx(0.1)


# --- T10 (c) positions: 슬리브별 percentile 맵 라우팅 + 단일 delete/upsert -------

async def test_eod_positions_use_own_sleeve_percentile_map(monkeypatch):
    _install_kis(
        monkeypatch,
        {
            AccountType.PAPER: _portfolio(
                [
                    _position("000002", unrealized_pl_rate=5.0),  # 주식(기본 fake percentile 0.1)
                    _position("069500", unrealized_pl_rate=5.0),  # ETF(기본 fake, remap 후 rank1)
                ],
                nav=500_000.0,
            ),
        },
    )
    monkeypatch.setattr(
        rating_batch,
        "get_universe",
        lambda universe, as_of=None, db_path=None: list(DEFAULT_ETF_CODES),
    )

    delete_spy = AsyncMock(side_effect=store.delete_position_ratings_for_accounts)
    upsert_spy = AsyncMock(side_effect=store.upsert_position_ratings)
    monkeypatch.setattr(store, "delete_position_ratings_for_accounts", delete_spy)
    monkeypatch.setattr(store, "upsert_position_ratings", upsert_spy)

    await rating_batch.run_rating_eod()

    delete_spy.assert_awaited_once()
    upsert_spy.assert_awaited_once()

    position_rows = {row["code"]: row for row in await store.get_position_ratings()}
    # 000002: 주식 슬리브 percentile 0.1 (기본 fake) -> SELL
    assert position_rows["000002"]["sell_grade"] == "SELL"
    assert position_rows["000002"]["reason"]["percentile"] == 0.1
    # 069500: ETF 슬리브, remap 후 rank1(score 최고) -> percentile 1.0 -> KEEP
    assert position_rows["069500"]["sell_grade"] == "KEEP"
    assert position_rows["069500"]["reason"]["rule"] == "SCORE_PERCENTILE"
    assert position_rows["069500"]["reason"]["percentile"] == 1.0


# --- T10 (d) ETF 전략 파일 누락 -> ETF 패스만 스킵, 주식 패스는 정상 완료 --------

async def test_eod_etf_strategy_missing_file_skips_etf_pass_with_warning(monkeypatch):
    _install_kis(
        monkeypatch,
        {
            AccountType.PAPER: _portfolio(
                [_position("000001", unrealized_pl_rate=5.0)], nav=500_000.0
            ),
        },
    )

    def _resolve_missing(name):
        if name == ETF_STRATEGY_NAME:
            raise FileNotFoundError(f"{name}.yaml not found")
        return _strategy(), None

    monkeypatch.setattr(rating_batch, "resolve_rating_strategy", _resolve_missing)

    summary = await rating_batch.run_rating_eod()

    assert summary["etf_strategy"] is None
    assert any("ETF strategy" in warning for warning in summary["warnings"])
    assert summary["error_count"] == 0

    # 주식 패스는 정상 완료 — 기본 stock fake의 3개 종목이 그대로 저장된다.
    stock_rows = await store.get_stock_ratings(["000001", "000002", "005930"])
    assert {row["code"] for row in stock_rows} == {"000001", "000002", "005930"}
    assert summary["stock_ratings_stored"] == 3  # etf 패스 스킵 -> stock 3건만


# --- INTRADAY: flips to SELL_NOW on breach, leaves other grades unchanged --------

async def test_intraday_flips_stop_loss_and_preserves_other_grades(monkeypatch):
    _install_kis(
        monkeypatch,
        {
            AccountType.PAPER: _portfolio(
                [
                    _position("000001", unrealized_pl_rate=-12.0),  # 손절 도달
                    _position("000002", unrealized_pl_rate=-2.0),  # 미도달
                ],
                nav=500_000.0,
            ),
        },
    )

    async with rating_batch.service_session() as session:
        session.add_all(
            [
                PositionRating(
                    broker=BrokerType.KIS.value, account_key="PAPER", code="000001",
                    sell_grade="KEEP", reason_json='{"rule": "SCORE_PERCENTILE", "percentile": 0.9}',
                    pl_rate=8.0, lane="EOD",
                ),
                PositionRating(
                    broker=BrokerType.KIS.value, account_key="PAPER", code="000002",
                    sell_grade="WATCH", reason_json='{"rule": "SCORE_PERCENTILE", "percentile": 0.3}',
                    pl_rate=-1.0, lane="EOD",
                ),
            ]
        )
        await session.commit()

    summary = await rating_batch.run_rating_intraday()
    assert summary["position_ratings_stored"] == 2

    position_rows = {row["code"]: row for row in await store.get_position_ratings()}
    assert position_rows["000001"]["sell_grade"] == "SELL_NOW"
    assert position_rows["000001"]["reason"]["rule"] == "STOP_LOSS"
    assert position_rows["000001"]["pl_rate"] == -12.0

    # 미도달분은 기존 등급/사유 유지, pl_rate만 갱신됨.
    assert position_rows["000002"]["sell_grade"] == "WATCH"
    assert position_rows["000002"]["reason"]["rule"] == "SCORE_PERCENTILE"
    assert position_rows["000002"]["pl_rate"] == -2.0

    latest = await store.latest_runs()
    assert latest["INTRADAY"]["stored_count"] == 2


# --- record_batch_run ------------------------------------------------------------

async def test_record_batch_run_writes_row():
    from datetime import datetime

    started = datetime(2026, 7, 24, 19, 0, 0)
    finished = datetime(2026, 7, 24, 19, 5, 0)
    await store.record_batch_run(
        lane="EOD", started_at=started, finished_at=finished,
        universe_size=10, stored_count=10, error_count=0, detail={"note": "ok"},
    )
    latest = await store.latest_runs()
    assert latest["EOD"]["universe_size"] == 10
    assert latest["EOD"]["detail"] == {"note": "ok"}


# --- rating_strategy_name setting read --------------------------------------------

async def test_read_rating_strategy_setting_prefers_db_value():
    async with rating_batch.service_session() as session:
        session.add(Setting(key="rating_strategy_name", value="value_v1"))
        await session.commit()

    resolved = await rating_batch._read_rating_strategy_setting()
    assert resolved == "value_v1"


async def test_read_rating_strategy_setting_none_when_absent():
    resolved = await rating_batch._read_rating_strategy_setting()
    assert resolved is None
