"""ISA 세금모델 — 과세 ETF 손익통산 + 비과세 한도 초과 9.9% (만기 정산 근사)."""
from __future__ import annotations

from datetime import date

import pytest

from research.backtest.tax_kr import ISATaxModel

TAXABLE = "133690"  # TIGER 미국나스닥100 — etf_taxable (kr_etf_tax_class.csv)


def test_within_exemption_no_tax():
    model = ISATaxModel()  # 기본 일반형 200만 공제
    assert model.gains_tax_for(TAXABLE, 1_500_000.0, date(2026, 3, 2)) == 0.0


def test_excess_only_taxed_at_9_9pct():
    model = ISATaxModel()
    tax = model.gains_tax_for(TAXABLE, 3_000_000.0, date(2026, 3, 2))
    assert tax == pytest.approx(0.099 * 1_000_000.0)


def test_netting_refunds_on_later_loss():
    model = ISATaxModel()
    charged = model.gains_tax_for(TAXABLE, 3_000_000.0, date(2026, 3, 2))
    refund = model.gains_tax_for(TAXABLE, -1_000_000.0, date(2026, 5, 2))
    assert charged == pytest.approx(0.099 * 1_000_000.0)
    assert refund == pytest.approx(-charged)  # 순이익 200만 → 세액 0으로 복귀


def test_stock_and_domestic_etf_untaxed():
    model = ISATaxModel()
    assert model.gains_tax_for("005930", 10_000_000.0, date(2026, 3, 2)) == 0.0
    # 069500 = KODEX 200 (etf_domestic_equity)
    assert model.gains_tax_for("069500", 10_000_000.0, date(2026, 3, 2)) == 0.0


def test_no_yearly_reset_maturity_settlement():
    """만기 일괄 정산 근사 — 연도가 바뀌어도 누적이 유지된다(US 모델과 차이)."""
    model = ISATaxModel()
    first = model.gains_tax_for(TAXABLE, 1_500_000.0, date(2025, 12, 20))
    second = model.gains_tax_for(TAXABLE, 1_500_000.0, date(2026, 1, 10))
    assert first == 0.0
    # 누적 300만 - 공제 200만 = 100만 초과분에 과세
    assert second == pytest.approx(0.099 * 1_000_000.0)


def test_seomin_exemption_400():
    model = ISATaxModel(exemption_krw=4_000_000)
    assert model.gains_tax_for(TAXABLE, 3_500_000.0, date(2026, 3, 2)) == 0.0
