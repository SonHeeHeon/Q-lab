"""Strategy resolution: private (gitignored) dir wins over the public dir.

Personal tuned equation weights live in research/strategies/private/ and are
never committed; the backend must pick them up transparently while a fresh
open-source clone (no private dir) still works off the public strategies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import backend.app.services.batch.daily_analysis as da

_PUBLIC_YAML = """
name: resolution_test
description: public copy
universe: KOSPI200
rebalance_freq: QUARTERLY
factors: []
filters: []
top_n: 5
start_date: 2020-01-01
end_date: 2020-12-31
"""

_PRIVATE_YAML = _PUBLIC_YAML.replace("public copy", "private copy").replace(
    "top_n: 5", "top_n: 7"
)


@pytest.fixture()
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    public = tmp_path / "strategies"
    private = public / "private"
    public.mkdir()
    private.mkdir()
    monkeypatch.setattr(da, "STRATEGY_DIR", public)
    monkeypatch.setattr(da, "PRIVATE_STRATEGY_DIR", private)
    return public, private


def test_private_wins_over_public(dirs):
    public, private = dirs
    (public / "resolution_test.yaml").write_text(_PUBLIC_YAML, encoding="utf-8")
    (private / "resolution_test.yaml").write_text(_PRIVATE_YAML, encoding="utf-8")
    strategy = da.load_strategy("resolution_test")
    assert strategy.description == "private copy"
    assert strategy.top_n == 7


def test_falls_back_to_public_without_private(dirs):
    public, _private = dirs
    (public / "resolution_test.yaml").write_text(_PUBLIC_YAML, encoding="utf-8")
    strategy = da.load_strategy("resolution_test")
    assert strategy.description == "public copy"


def test_missing_everywhere_raises(dirs):
    with pytest.raises(FileNotFoundError, match="private/"):
        da.load_strategy("nope")
