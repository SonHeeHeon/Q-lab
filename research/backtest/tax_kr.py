"""KR listed-instrument tax classification + display-purpose sell/gains tax estimates.

Scope is deliberately KR-only (2026 tax rules, user-confirmed):

- KR listed stock (minority/소액주주 holder): no capital gains tax; only
  증권거래세 applies on sells. ``KR_STOCK_SELL_TAX_RATE`` below is a
  *display-purpose* rate and is intentionally kept separate from
  ``research.backtest.simulator.CostModel.sell_tax_rate`` (0.0023), which is a
  historical backtest-calibration average for a different purpose — do not
  merge or resync the two constants.
- KR listed ETF sells: no 증권거래세 at all, ever. Whether the *매매차익*
  (trading gain) itself is taxed depends on the ETF's class:
  - 국내주식형(domestic_equity): 비과세 (매매차익 tax-free).
  - 기타/해외/채권/파생(taxable): 배당소득세 15.4% withheld on positive gains,
    per sale — no cross-position loss offset. This immediate per-sale model
    is intentional (mirrors withholding-at-source), not a simplification of
    annual netting.
- Approximation note: the real tax base is
  ``min(매매차익, 과표기준가 증분)``; this module uses the average-entry-price
  gain instead (과표기준가/box-price data isn't available here), so every
  taxable-ETF estimate carries a ``tax_note`` caveat.

Pure/no DB — the only IO is a best-effort read of the manual classification
CSV — so this is usable directly from ``research/`` and re-exported as a thin
wrapper by ``backend/app/services/tax/kr.py``.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TAX_CLASS_FILE = PROJECT_ROOT / "data" / "manual" / "kr_etf_tax_class.csv"
# Optional auto-generated companion (same dir, same format). May not exist —
# tolerated exactly like TAX_CLASS_FILE. Manual entries always win on merge.
AUTO_TAX_CLASS_FILE = PROJECT_ROOT / "data" / "manual" / "kr_etf_tax_class.auto.csv"

# 국내 상장주식(소액주주) 매도 시 증권거래세 — 표시용 개략 세율.
# research.backtest.simulator.CostModel.sell_tax_rate(0.0023)는 백테스트 비용
# 보정용 별도 상수이며 용도가 다르므로 이 값과 절대 동기화하지 않는다.
KR_STOCK_SELL_TAX_RATE = 0.0015

# 국내 상장 ETF 중 과세 대상(기타/해외/채권/파생) 매매차익에 매기는 배당소득세율.
ETF_TAXABLE_GAINS_RATE = 0.154

_CODE_RE = re.compile(r"^\d{6}$")

_tax_class_cache: dict[str, str] | None = None
_tax_class_warnings: list[str] = []


def _read_tax_class_csv(path: Path, *, required: bool) -> dict[str, str]:
    """Read one ``code -> tax_class`` CSV, tolerant of the file being absent.

    ``required`` only affects the warning message; a missing file always
    yields an empty mapping rather than raising, since callers should never
    crash on a fresh checkout that hasn't populated the manual CSV yet, nor
    on an environment that hasn't generated the optional auto CSV.
    """
    mapping: dict[str, str] = {}
    if not path.exists():
        if required:
            _tax_class_warnings.append(f"tax class file missing: {path}")
        return mapping

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(
                line for line in fh if line.strip() and not line.lstrip().startswith("#")
            )
            for row in reader:
                code = (row.get("code") or "").strip()
                tax_class = (row.get("tax_class") or "").strip()
                if code and tax_class:
                    mapping[code] = tax_class
    except OSError as exc:
        _tax_class_warnings.append(f"failed to read tax class file: {exc}")
        return {}

    return mapping


def _load_tax_class_map() -> dict[str, str]:
    """Lazily load + cache the merged ``code -> tax_class`` mapping.

    Merges the optional auto-generated ``AUTO_TAX_CLASS_FILE`` with the
    manual ``TAX_CLASS_FILE``, manual entries taking precedence on
    conflict. Either file may be absent (tolerated, same as before this
    merge was introduced).
    """
    global _tax_class_cache
    if _tax_class_cache is not None:
        return _tax_class_cache

    auto_map = _read_tax_class_csv(AUTO_TAX_CLASS_FILE, required=False)
    manual_map = _read_tax_class_csv(TAX_CLASS_FILE, required=True)

    mapping = {**auto_map, **manual_map}
    _tax_class_cache = mapping
    return mapping


def classify_kr_instrument(code: str, *, is_etf: bool | None = None) -> str:
    """Classify a KR instrument code for display-purpose tax estimation.

    Returns one of ``"stock" | "etf_domestic_equity" | "etf_taxable" | "unknown"``.

    - A code registered in ``kr_etf_tax_class.csv`` returns its listed class
      (``domestic_equity`` -> ``etf_domestic_equity``, ``taxable`` ->
      ``etf_taxable``), regardless of ``is_etf``.
    - A plain 6-digit code absent from the CSV is assumed to be a stock —
      *unless* the caller already knows it is an ETF (``is_etf=True``): an
      ETF missing from the CSV must never be silently taxed like a stock, so
      that case returns ``unknown`` instead.
    - Anything that isn't a 6-digit code (e.g. a US ticker like ``AAPL``) is
      ``unknown``.
    """
    if not code or not _CODE_RE.match(code):
        return "unknown"

    tax_class = _load_tax_class_map().get(code)
    if tax_class == "domestic_equity":
        return "etf_domestic_equity"
    if tax_class == "taxable":
        return "etf_taxable"

    if is_etf:
        return "unknown"
    return "stock"


def estimate_sell_tax(
    code: str,
    qty: int,
    price: float,
    entry_price: float,
    *,
    is_etf: bool | None = None,
    classification: str | None = None,
) -> dict:
    """Display-purpose sell tax + realized-gain tax estimate for one sale.

    Returns ``{"tax_type", "est_sell_tax", "est_gains_tax", "tax_note"}``.
    ``classification`` lets a caller pass an already-resolved
    ``classify_kr_instrument`` result to skip re-classifying.
    """
    tax_class = classification or classify_kr_instrument(code, is_etf=is_etf)

    if tax_class == "stock":
        return {
            "tax_type": tax_class,
            "est_sell_tax": qty * price * KR_STOCK_SELL_TAX_RATE,
            "est_gains_tax": 0.0,
            "tax_note": "국내 상장주식(소액주주): 매도 시 증권거래세만 부과, 매매차익 비과세",
        }

    if tax_class == "etf_domestic_equity":
        return {
            "tax_type": tax_class,
            "est_sell_tax": 0.0,
            "est_gains_tax": 0.0,
            "tax_note": "국내주식형 ETF: 증권거래세 없음, 매매차익 비과세",
        }

    if tax_class == "etf_taxable":
        gain = max((price - entry_price) * qty, 0.0)
        return {
            "tax_type": tax_class,
            "est_sell_tax": 0.0,
            "est_gains_tax": ETF_TAXABLE_GAINS_RATE * gain,
            "tax_note": (
                "기타/해외/채권/파생 ETF: 증권거래세 없음, 매매차익 배당소득세 15.4% "
                "원천징수(건별 계산, 손익 통산 미적용). "
                "평균단가 기준 근사(과표기준가 미반영)"
            ),
        }

    return {
        "tax_type": tax_class,
        "est_sell_tax": 0.0,
        "est_gains_tax": 0.0,
        "tax_note": "과세 분류 미등록",
    }


class TaxModel(BaseModel):
    """KR capital-gains tax assumptions for after-tax backtests (v1: ETF only).

    Engine-pluggable counterpart to ``estimate_sell_tax``'s taxable-ETF
    branch: a stateful, pydantic model (mirrors ``simulator.CostModel``)
    rather than a one-shot display estimate. Stock capital gains are untaxed
    for a minority holder (``classify_kr_instrument`` returns ``"stock"``),
    so this only ever produces a nonzero tax for ``etf_taxable`` codes.
    """

    etf_taxable_gains_rate: float = ETF_TAXABLE_GAINS_RATE

    def gains_tax_for(self, code: str, realized_gain: float) -> float:
        """Capital-gains tax owed on one SELL's realized gain.

        Only a taxable ETF (``classify_kr_instrument(code) ==
        "etf_taxable"``) with a positive realized gain owes anything —
        mirrors the per-sale withholding model in ``estimate_sell_tax``
        (no cross-position loss offset).
        """
        if realized_gain <= 0:
            return 0.0
        if classify_kr_instrument(code) != "etf_taxable":
            return 0.0
        return self.etf_taxable_gains_rate * realized_gain


# US universes have no v1 after-tax support (KR capital-gains tax rules only).
_TAX_UNSUPPORTED_UNIVERSES = {"NASDAQ100", "ETF_US"}


def default_tax_model_for_universe(universe: str) -> TaxModel | None:
    """Default ``TaxModel`` for a backtest universe, or ``None`` if unsupported.

    KR universes (including ``ETF_KR``) get a ``TaxModel()``: plain stock
    universes realize zero tax anyway (``classify_kr_instrument`` returns
    ``"stock"``), so this is a no-op cost for them and only matters for
    ``ETF_KR``. US universes return ``None`` — after-tax modeling for US
    capital gains is out of scope for v1.
    """
    if universe.upper() in _TAX_UNSUPPORTED_UNIVERSES:
        return None
    return TaxModel()
