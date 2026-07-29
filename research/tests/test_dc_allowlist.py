"""DC allowlist CSV 로더 (계좌 프로파일 프레임워크 1호)."""
from __future__ import annotations

from pathlib import Path

from research.universe.dc_kis import DC_ALLOWLIST_FILE, load_dc_allowlist


def test_load_dc_allowlist_parses_classes(tmp_path: Path):
    csv_file = tmp_path / "allow.csv"
    csv_file.write_text(
        "# comment\ncode,name,risk_class,memo\n"
        "069500,KODEX 200,risk,국내 대형주\n"
        "153130,KODEX 단기채권,safe,단기채\n"
        "999999,BAD,unknown_class,잘못된 분류는 무시\n",
        encoding="utf-8",
    )
    mapping = load_dc_allowlist(csv_file)
    assert mapping == {"069500": "risk", "153130": "safe"}


def test_load_dc_allowlist_missing_file_returns_empty(tmp_path: Path):
    assert load_dc_allowlist(tmp_path / "absent.csv") == {}


def test_seed_csv_exists_and_valid():
    """시드 CSV 구조 검증: 파일 존재 + risk/safe 최소 개수 + 6자리 코드."""
    mapping = load_dc_allowlist(DC_ALLOWLIST_FILE)
    assert len([c for c, k in mapping.items() if k == "risk"]) >= 5
    assert len([c for c, k in mapping.items() if k == "safe"]) >= 3
    assert all(c.isdigit() and len(c) == 6 for c in mapping)
