"""DC 전략 yaml 2종 로드 스모크."""
from backend.app.services.batch.daily_analysis import load_strategy


def test_dc_risk_rotation_loads():
    s = load_strategy("dc_risk_rotation_kr")
    assert s.universe == "ETF_KR_DC_RISK"
    assert s.rebalance_freq == "MONTHLY"
    assert s.top_n == 3
    assert s.groups and s.groups[0].name == "Momentum"


def test_dc_safe_rotation_loads():
    s = load_strategy("dc_safe_rotation_kr")
    assert s.universe == "ETF_KR_DC_SAFE"
    assert s.top_n == 2
