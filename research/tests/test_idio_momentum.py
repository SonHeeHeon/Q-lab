"""잔차(시장조정) 모멘텀 테스트 (Phase 4.3 후보 C).

IDIO_MOM = 종목수익률 − 같은 창의 KOSPI 수익률. 시장과 함께 오른 종목은 ~0,
시장을 초과한 종목만 양(+)이 되는지 검증한다.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from research.backtest.engine import _factor_series
from research.factors.momentum import calculate_named_idio_momentum

AS_OF = date(2026, 6, 30)
LOOKBACK = 63  # IDIO_MOM_3M


def _make_db(tmp_path: Path, *, with_market: bool = True) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT,"
            " close REAL, adj_close REAL)"
        )
        conn.execute(
            "CREATE TABLE market_index (index_code TEXT, date TEXT, close REAL)"
        )
        # LOOKBACK+1 거래일 생성. 시장은 +10% 상승. (KR 라우팅 위해 숫자 코드 사용)
        # 000001 (MKTUP):  종목도 +10% (시장과 동일) → IDIO ≈ 0
        # 000002 (OUTPERF): +21% (시장 초과)         → IDIO ≈ +0.11
        days = []
        d = AS_OF
        while len(days) < LOOKBACK + 1:
            if d.weekday() < 5:
                days.append(d)
            d -= timedelta(days=1)
        days = sorted(days)
        n = len(days) - 1
        for i, day in enumerate(days):
            frac = i / n
            iso = day.isoformat()
            conn.execute("INSERT INTO prices_daily VALUES (?,?,?,NULL)",
                         ("000001", iso, 100.0 * (1 + 0.10 * frac)))
            conn.execute("INSERT INTO prices_daily VALUES (?,?,?,NULL)",
                         ("000002", iso, 100.0 * (1 + 0.21 * frac)))
            if with_market:
                conn.execute("INSERT INTO market_index VALUES ('KOSPI',?,?)",
                             (iso, 2000.0 * (1 + 0.10 * frac)))
    return path


def test_market_matcher_has_near_zero_idio(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    s = calculate_named_idio_momentum("IDIO_MOM_3M", ["000001"], as_of=AS_OF, db_path=db)
    # 종목 +10%, 시장 +10% → 잔차 ≈ 0
    assert s["000001"] == pytest.approx(0.0, abs=1e-6)


def test_outperformer_has_positive_idio(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    s = calculate_named_idio_momentum("IDIO_MOM_3M", ["000002"], as_of=AS_OF, db_path=db)
    # 종목 +21%, 시장 +10% → 잔차 ≈ +0.11
    assert s["000002"] == pytest.approx(0.11, abs=1e-6)


def test_engine_dispatches_idio_before_plain_momentum(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    idio = _factor_series("IDIO_MOM_3M", ["000002"], as_of=AS_OF, db_path=db, warnings=[])
    plain = _factor_series("MOMENTUM_3M", ["000002"], as_of=AS_OF, db_path=db, warnings=[])
    assert idio["000002"] == pytest.approx(0.11, abs=1e-6)
    assert plain["000002"] == pytest.approx(0.21, abs=1e-6)  # 시장 미조정


def test_degrades_to_plain_when_market_absent(tmp_path: Path) -> None:
    # 시장 시계열이 없으면 시장 다리=0 → 순수 모멘텀으로 강등(전 종목 드롭 아님).
    db = _make_db(tmp_path, with_market=False)
    s = calculate_named_idio_momentum("IDIO_MOM_3M", ["000002"], as_of=AS_OF, db_path=db)
    assert s["000002"] == pytest.approx(0.21, abs=1e-6)
