"""KR ETF tax-class AUTO-classifier (pykrx deposit-file based).

Runs in the user's real environment (where KRX/pykrx endpoints actually
respond — unlike this dev sandbox) to classify newly-listed ETFs into the
same ``domestic_equity`` / ``taxable`` buckets used by the hand-curated
``data/manual/kr_etf_tax_class.csv``. Output goes to a SEPARATE file,
``data/manual/kr_etf_tax_class.auto.csv``, which ``research.backtest.tax_kr``
merges UNDER the manual file (manual entries always win) — that merge is a
different task; this module only classifies and writes the auto CSV.

Classification is conservative: an ETF that can't be confidently classified
as tax-exempt is always labeled ``taxable`` rather than risk mislabeling a
taxable fund as exempt.

1. Name-marker fast path: if the ETF name contains an obvious foreign /
   bond / commodity / derivative / leverage marker (``TAXABLE_NAME_MARKERS``),
   classify ``taxable`` immediately — no holdings lookup needed.
2. Otherwise, fetch the constituent holdings (PDF — portfolio deposit file).
   If (nearly) all constituent tickers are 6-digit KR stock codes, the ETF
   is a domestic-equity fund (``domestic_equity``); otherwise ``taxable``.
3. Any failure along the way (name lookup error, deposit-file error,
   exception, or empty holdings) defaults to ``taxable`` with a logged
   warning — never fails open into ``domestic_equity``.

Pure/no DB, network access only through the injectable ``deposit_file_fn`` /
``name_fn`` callables (each lazily imports ``pykrx`` by default, mirroring
``research.data_ingestion.pykrx_loader._pykrx_stock()``), so this module is
fully unit-testable offline with mocks and safe to import from anywhere in
``research/`` (no ``backend`` import).

CLI usage — run this in an environment with working KRX/pykrx access to
classify newly-added ETF codes and (re)write the auto CSV:

    .venv/bin/python -c "
    from pathlib import Path
    from research.data_ingestion.etf_tax_classifier import build_auto_tax_csv
    build_auto_tax_csv(
        ['069500', '091160'],
        Path('data/manual/kr_etf_tax_class.auto.csv'),
    )
    "
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Callable
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DOMESTIC_EQUITY = "domestic_equity"
TAXABLE = "taxable"

# ETF name substrings that mark a fund as foreign / bond / commodity /
# derivative / leveraged -> always `taxable`, regardless of holdings.
TAXABLE_NAME_MARKERS: tuple[str, ...] = (
    "인버스",
    "레버리지",
    "곱버스",
    "2X",
    "선물",
    "채권",
    "국고채",
    "미국",
    "해외",
    "글로벌",
    "S&P",
    "나스닥",
    "골드",
    "원유",
    "은",
    "달러",
    "리츠",
    "차이나",
    "베트남",
    "인도",
    "신흥국",
    "선진국",
    "(H)",
    "MSCI",
    "CSI",
)

# "은" (silver, e.g. "KODEX 은선물(H)") is the one single-character marker in
# the set above, and it collides with the unrelated common word "은행"
# (bank) — e.g. "KODEX 은행" must NOT be flagged purely from that substring.
# All other markers are multi-char and unambiguous, so a plain substring
# check is used for them; "은" alone gets this negative-lookahead guard.
_SILVER_MARKER_RE = re.compile(r"은(?!행)")

_KR_CODE_RE = re.compile(r"^\d{6}$")
_MIN_KR_HOLDINGS_RATIO = 0.8


def _pykrx_stock():
    from pykrx import stock

    return stock


def _default_name_fn(code: str) -> str:
    return _pykrx_stock().get_etf_ticker_name(code)


def _default_deposit_file_fn(code: str) -> pd.DataFrame:
    return _pykrx_stock().get_etf_portfolio_deposit_file(code)


def _name_has_taxable_marker(name: str) -> bool:
    for marker in TAXABLE_NAME_MARKERS:
        if marker == "은":
            if _SILVER_MARKER_RE.search(name):
                return True
            continue
        if marker in name:
            return True
    return False


def _classify(
    code: str,
    deposit_file_fn: Callable[[str], pd.DataFrame],
    name_fn: Callable[[str], str],
) -> tuple[str, str]:
    """Returns ``(name, tax_class)``; ``name`` is ``""`` if lookup failed."""
    try:
        name = name_fn(code) or ""
    except Exception as exc:
        logger.warning("etf_tax_classifier: name lookup failed for %s: %s", code, exc)
        return "", TAXABLE

    if _name_has_taxable_marker(name):
        return name, TAXABLE

    try:
        holdings = deposit_file_fn(code)
    except Exception as exc:
        logger.warning(
            "etf_tax_classifier: deposit file lookup failed for %s (%s): %s",
            code,
            name,
            exc,
        )
        return name, TAXABLE

    if holdings is None or holdings.empty:
        logger.warning(
            "etf_tax_classifier: empty holdings for %s (%s); defaulting to taxable",
            code,
            name,
        )
        return name, TAXABLE

    tickers = [str(t) for t in holdings.index]
    kr_count = sum(1 for t in tickers if _KR_CODE_RE.match(t))
    ratio = kr_count / len(tickers) if tickers else 0.0

    if ratio >= _MIN_KR_HOLDINGS_RATIO:
        return name, DOMESTIC_EQUITY
    return name, TAXABLE


def classify_etf_tax(
    code: str,
    *,
    deposit_file_fn: Callable[[str], pd.DataFrame] | None = None,
    name_fn: Callable[[str], str] | None = None,
) -> str:
    """Classify one KR ETF code as ``"domestic_equity"`` or ``"taxable"``.

    See the module docstring for the 3-step conservative decision rule.
    ``deposit_file_fn`` / ``name_fn`` default to lazy ``pykrx`` calls but can
    be injected for offline testing.
    """
    deposit_file_fn = deposit_file_fn or _default_deposit_file_fn
    name_fn = name_fn or _default_name_fn
    _, tax_class = _classify(code, deposit_file_fn, name_fn)
    return tax_class


def build_auto_tax_csv(
    codes: list[str],
    out_path: Path,
    *,
    deposit_file_fn: Callable[[str], pd.DataFrame] | None = None,
    name_fn: Callable[[str], str] | None = None,
) -> dict[str, int]:
    """Classify ``codes`` and write ``code,tax_class,name`` rows to ``out_path``.

    Same 3-column format as the manual CSV
    (``data/manual/kr_etf_tax_class.csv``), so ``research.backtest.tax_kr``'s
    tolerant reader can load it unchanged. Returns a counts summary:
    ``{"domestic_equity": N, "taxable": N, "total": N}``.
    """
    deposit_file_fn = deposit_file_fn or _default_deposit_file_fn
    name_fn = name_fn or _default_name_fn

    counts = {DOMESTIC_EQUITY: 0, TAXABLE: 0, "total": 0}
    rows: list[tuple[str, str, str]] = []

    for code in codes:
        name, tax_class = _classify(code, deposit_file_fn, name_fn)
        rows.append((code, tax_class, name))
        counts[tax_class] += 1
        counts["total"] += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["code", "tax_class", "name"])
        writer.writerows(rows)

    return counts
