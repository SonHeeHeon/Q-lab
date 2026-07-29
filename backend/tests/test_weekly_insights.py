"""주간 슬리브 인사이트 구성 검증."""
from __future__ import annotations

from backend.app.services.batch.daily_analysis import SLEEVE_INSIGHT_STRATEGIES


def test_sleeve_insight_strategies_includes_dc_risk():
    """DC 위험 슬리브 랭킹은 자문(수동 매매) 참고용으로 주간 갱신에 포함된다.

    안전 슬리브는 A/B 결과 '단기채권 고정 보유' 채택(로테이션 기각)이라
    랭킹을 노출하지 않는다 — dc_safe가 다시 늘어나면 채택 근거부터 재검토할 것.
    """
    mapping = dict(SLEEVE_INSIGHT_STRATEGIES)
    assert mapping.get("dc_risk") == "dc_risk_rotation_kr"
    assert "dc_safe" not in mapping
