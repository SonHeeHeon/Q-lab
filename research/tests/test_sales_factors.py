"""PSR · OP_MARGIN factor tests (Phase 4.3 후보 B).

매출·영업이익도 net_income과 동일한 KR mixed-annual TTM 재구성을 거치는지, 그리고
음수/결측 매출이 안전하게 NA가 되는지 검증한다.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from research.backtest.engine import _factor_series
from research.factors.quality import calculate_op_margin, calculate_quality_factors
from research.factors.value import calculate_psr

AS_OF = date(2026, 6, 30)


def _make_db(tmp_path: Path, *, with_sales_cols: bool = True) -> Path:
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        sales_cols = ", revenue REAL, operating_income REAL" if with_sales_cols else ""
        conn.execute(
            "CREATE TABLE financials (id INTEGER PRIMARY KEY, stock_code TEXT,"
            " fiscal_period TEXT, disclosed_at TEXT, net_income REAL,"
            f" total_equity REAL, total_assets REAL, eps REAL, bps REAL{sales_cols})"
        )
        conn.execute(
            "CREATE TABLE prices_daily (stock_code TEXT, date TEXT,"
            " close REAL, adj_close REAL)"
        )
        # 005930: Q1~Q3-25 interims + Annual-25 + Q1-26. Annual must NOT double-count.
        #   revenue TTM(Q1-26..Q2-25) = 130 + (500-330) + 120 + 110 = 530
        #   op TTM = 13 + (50-33) + 12 + 11 = 53 → OP_MARGIN = 53/530 = 0.10
        if with_sales_cols:
            rows = [
                ("005930", "2025-03-31", "2025-05-15", 8.0, None, None, None, None, 100.0, 10.0),
                ("005930", "2025-06-30", "2025-08-14", 8.0, None, None, None, None, 110.0, 11.0),
                ("005930", "2025-09-30", "2025-11-14", 8.0, None, None, None, None, 120.0, 12.0),
                ("005930", "2025-12-31", "2026-03-12", 40.0, None, None, None, None, 500.0, 50.0),
                # 최신 공시(Q1-26): 주식수 도출용 net_income/eps → shares = 10/0.01 = 1000
                ("005930", "2026-03-31", "2026-05-16", 10.0, 4000.0, 8000.0, 0.01, None, 130.0, 13.0),
            ]
            conn.executemany(
                "INSERT INTO financials (stock_code, fiscal_period, disclosed_at,"
                " net_income, total_equity, total_assets, eps, bps, revenue,"
                " operating_income) VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            # 음수 매출 종목 → PSR/OP_MARGIN NA.
            conn.execute(
                "INSERT INTO financials (stock_code, fiscal_period, disclosed_at,"
                " net_income, total_equity, total_assets, eps, bps, revenue,"
                " operating_income) VALUES ('444444','2026-03-31','2026-05-16',"
                " 1.0, 100.0, 200.0, 0.01, NULL, -50.0, -5.0)"
            )
        else:
            conn.execute(
                "INSERT INTO financials (stock_code, fiscal_period, disclosed_at,"
                " net_income, total_equity, total_assets, eps, bps)"
                " VALUES ('005930','2026-03-31','2026-05-16',10.0,4000.0,8000.0,0.01,NULL)"
            )
        conn.execute(
            "INSERT INTO prices_daily VALUES ('005930','2026-06-30',53.0,NULL)"
        )
    return path


def test_op_margin_uses_reconstructed_ttm_no_double_count(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    opm = calculate_op_margin(["005930"], as_of=AS_OF, db_path=db)
    # 53/530 = 0.10. 잘못된 sum-of-last-4는 (13+50+12+11)/(130+500+120+110)=86/860≈0.10?
    # → 분자·분모 모두 부풀지만 비율은 우연히 비슷할 수 있으니 정확값으로 검증.
    assert opm["005930"] == pytest.approx(0.10, rel=1e-6)


def test_psr_is_price_over_sales_per_share(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    psr = calculate_psr(["005930"], as_of=AS_OF, db_path=db)
    # revenue_ttm=530, shares=net_income/eps=10/0.01=1000 → SPS=0.53
    # PSR = price(53) / 0.53 = 100
    assert psr["005930"] == pytest.approx(100.0, rel=1e-6)


def test_negative_revenue_is_na(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    psr = calculate_psr(["444444"], as_of=AS_OF, db_path=db)
    opm = calculate_op_margin(["444444"], as_of=AS_OF, db_path=db)
    assert "444444" not in psr.dropna().index
    assert "444444" not in opm.dropna().index


def test_engine_dispatches_psr_and_op_margin(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    psr = _factor_series("PSR", ["005930"], as_of=AS_OF, db_path=db, warnings=[])
    opm = _factor_series("OP_MARGIN", ["005930"], as_of=AS_OF, db_path=db, warnings=[])
    assert psr["005930"] == pytest.approx(100.0, rel=1e-6)
    assert opm["005930"] == pytest.approx(0.10, rel=1e-6)


def test_graceful_when_sales_columns_absent(tmp_path: Path) -> None:
    # 매출 컬럼이 없는 (구/테스트) 스키마 → PSR/OP_MARGIN은 조용히 비고, ROE 등은 정상.
    db = _make_db(tmp_path, with_sales_cols=False)
    psr = calculate_psr(["005930"], as_of=AS_OF, db_path=db)
    opm = calculate_op_margin(["005930"], as_of=AS_OF, db_path=db)
    assert psr.dropna().empty
    assert opm.dropna().empty
    # 회귀: ROE는 net_income/equity로 여전히 계산돼야 한다.
    frame = calculate_quality_factors(["005930"], as_of=AS_OF, db_path=db)
    assert frame.loc["005930", "ROE"] == pytest.approx(10.0 / 4000.0)
