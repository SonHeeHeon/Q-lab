"""US 양도소득세 모델(연간 손익통산·공제·연도 리셋) + US 비용/세금 라우팅."""

from __future__ import annotations

from datetime import date

import pytest

from research.backtest.simulator import (
    US_COST_MODEL,
    default_cost_model_for_universe,
)
from research.backtest.tax_kr import (
    USCapitalGainsTaxModel,
    default_tax_model_for_universe,
)


def _model() -> USCapitalGainsTaxModel:
    return USCapitalGainsTaxModel()


def test_below_exemption_no_tax():
    m = _model()
    assert m.gains_tax_for("AAPL", 1000.0, date(2024, 3, 1)) == 0.0


def test_above_exemption_taxes_excess_only():
    m = _model()
    exempt = m.annual_exemption_usd
    tax = m.gains_tax_for("AAPL", exempt + 1000.0, date(2024, 3, 1))
    assert tax == pytest.approx(0.22 * 1000.0)


def test_annual_netting_refunds_on_later_loss():
    m = _model()
    exempt = m.annual_exemption_usd
    first = m.gains_tax_for("AAPL", exempt + 2000.0, date(2024, 3, 1))
    assert first == pytest.approx(0.22 * 2000.0)
    # 같은 해 손실 → 연 순이익 재계산, 초과 부과분 환급(음수)
    second = m.gains_tax_for("MSFT", -1500.0, date(2024, 9, 1))
    assert second == pytest.approx(-0.22 * 1500.0)
    # 연간 합계 = 순이익(500) 초과분 기준
    assert first + second == pytest.approx(0.22 * 500.0)


def test_year_rollover_resets_accumulation():
    m = _model()
    exempt = m.annual_exemption_usd
    m.gains_tax_for("AAPL", exempt + 5000.0, date(2024, 6, 1))
    # 새 해: 누적·공제 리셋 → 공제 이하 이익은 무세
    assert m.gains_tax_for("AAPL", 100.0, date(2025, 1, 15)) == 0.0


def test_loss_only_year_never_negative_total():
    m = _model()
    assert m.gains_tax_for("AAPL", -3000.0, date(2024, 2, 1)) == 0.0
    assert m.gains_tax_for("MSFT", -500.0, date(2024, 5, 1)) == 0.0


def test_universe_routing():
    # US 유니버스 → 연간 모델, KR → 기본 KR 모델(과세 ETF per-sell)
    assert isinstance(default_tax_model_for_universe("US_LARGE"), USCapitalGainsTaxModel)
    assert isinstance(default_tax_model_for_universe("ETF_US"), USCapitalGainsTaxModel)
    kr = default_tax_model_for_universe("KOSPI200")
    assert kr is not None and not isinstance(kr, USCapitalGainsTaxModel)
    # 비용모델: US_LARGE가 KR 매도세(0.23%)를 물지 않는다(회귀 방지)
    assert default_cost_model_for_universe("US_LARGE") is US_COST_MODEL
    assert default_cost_model_for_universe("US_LARGE").sell_tax_rate == 0.0
