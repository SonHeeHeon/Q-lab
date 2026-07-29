"""DC 유니버스(ETF_KR_DC_RISK/SAFE) 배선: get_universe·비용·세금 모델."""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

import research.universe.dc_kis as dc_kis
from research.backtest.engine import get_universe
from research.backtest.simulator import (
    KR_ETF_COST_MODEL,
    default_cost_model_for_universe,
)
from research.backtest.tax_kr import default_tax_model_for_universe
from shared.domain.strategy import StrategyDefinition


@pytest.fixture()
def dc_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "research.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE stocks (code TEXT, name TEXT, market TEXT,"
            " listed_at TEXT, delisted_at TEXT)"
        )
        rows = [
            ("069500", "KODEX 200", "ETF", "2016-01-04", None),
            ("153130", "KODEX 단기채권", "ETF", "2016-01-04", None),
            ("122630", "KODEX 레버리지", "ETF", "2016-01-04", None),  # 제외돼야 함
            ("005930", "삼성전자", "KOSPI", "2016-01-04", None),      # ETF 아님
            ("999990", "미등록 ETF", "ETF", "2016-01-04", None),      # allowlist 밖
        ]
        conn.executemany("INSERT INTO stocks VALUES (?,?,?,?,?)", rows)
    allow = tmp_path / "allow.csv"
    allow.write_text(
        "code,name,risk_class,memo\n069500,KODEX 200,risk,\n"
        "153130,KODEX 단기채권,safe,\n122630,KODEX 레버리지,risk,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dc_kis, "DC_ALLOWLIST_FILE", allow)
    return db


def test_dc_risk_universe_filters_allowlist_and_leverage(dc_db: Path):
    codes = get_universe("ETF_KR_DC_RISK", as_of=date(2026, 7, 1), db_path=dc_db)
    assert codes == ["069500"]  # 레버리지(122630)·미등록(999990)·비ETF 제외


def test_dc_safe_universe(dc_db: Path):
    codes = get_universe("ETF_KR_DC_SAFE", as_of=date(2026, 7, 1), db_path=dc_db)
    assert codes == ["153130"]


def test_dc_universes_use_kr_etf_cost_model():
    assert default_cost_model_for_universe("ETF_KR_DC_RISK") is KR_ETF_COST_MODEL
    assert default_cost_model_for_universe("ETF_KR_DC_SAFE") is KR_ETF_COST_MODEL


def test_dc_universes_are_tax_deferred():
    assert default_tax_model_for_universe("ETF_KR_DC_RISK") is None
    assert default_tax_model_for_universe("ETF_KR_DC_SAFE") is None


def test_strategy_definition_accepts_dc_universes():
    payload = dict(
        name="t", description="t", universe="ETF_KR_DC_RISK",
        rebalance_freq="MONTHLY", factors=[], filters=[], top_n=3,
        start_date=date(2016, 7, 1), end_date=date(2026, 7, 1),
    )
    assert StrategyDefinition.model_validate(payload).universe == "ETF_KR_DC_RISK"
