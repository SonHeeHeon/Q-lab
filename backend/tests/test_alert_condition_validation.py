"""Alert-condition creation validation (P1 dead-alert guard).

VOLUME_SPIKE is accepted by the wire enum but the evaluator raises for it, so a
created VOLUME_SPIKE alert errors on every cycle forever. AlertCreate now
rejects it at construction (→ 422) with a clear message.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.api.alerts import AlertCreate


def _payload(condition: str) -> dict:
    return {
        "stock_code": "005930",
        "condition": condition,
        "threshold": 70000.0,
    }


def test_volume_spike_rejected_at_creation():
    with pytest.raises(ValidationError, match="VOLUME_SPIKE alerts are not supported"):
        AlertCreate(**_payload("VOLUME_SPIKE"))


@pytest.mark.parametrize("condition", ["PRICE_ABOVE", "PRICE_BELOW", "PCT_CHANGE"])
def test_supported_conditions_accepted(condition: str):
    alert = AlertCreate(**_payload(condition))
    assert alert.condition == condition
