"""KIS DC(퇴직연금) 매매 가능 ETF allowlist 로더 — 계좌 프로파일 프레임워크.

CSV는 data/manual/account_profiles/kis_dc_etf_allowlist.csv (수동 유지보수,
kr_etf_tax_class.csv와 동일한 관용구). risk_class: risk=위험자산, safe=안전자산.
"""
from __future__ import annotations

import csv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DC_ALLOWLIST_FILE = (
    PROJECT_ROOT / "data" / "manual" / "account_profiles" / "kis_dc_etf_allowlist.csv"
)
VALID_CLASSES = {"risk", "safe"}


def load_dc_allowlist(path: Path | None = None) -> dict[str, str]:
    """``code -> "risk"|"safe"`` 매핑. 파일이 없으면 빈 dict(신규 체크아웃 허용)."""
    target = path or DC_ALLOWLIST_FILE
    if not target.exists():
        return {}
    mapping: dict[str, str] = {}
    with target.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(
            line for line in fh if line.strip() and not line.lstrip().startswith("#")
        )
        for row in reader:
            code = (row.get("code") or "").strip()
            risk_class = (row.get("risk_class") or "").strip()
            if code and risk_class in VALID_CLASSES:
                mapping[code] = risk_class
    return mapping
