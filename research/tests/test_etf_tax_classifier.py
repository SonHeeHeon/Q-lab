"""KR ETF tax AUTO-classifier tests (research/data_ingestion/etf_tax_classifier.py).

All pykrx access is mocked via the injectable ``deposit_file_fn`` / ``name_fn``
params — no network calls (this sandbox's pykrx KRX endpoints return empty
anyway, so the module must be fully testable offline).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from research.data_ingestion import etf_tax_classifier as m


def _deposit_df(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"계약수": [1.0] * len(tickers), "금액": [1] * len(tickers), "비중": [1.0] * len(tickers)},
        index=pd.Index(tickers, name="티커"),
    )


class _NotCalled:
    """Deposit-file stub that fails the test if it's ever invoked."""

    def __call__(self, code: str) -> pd.DataFrame:
        pytest.fail(f"deposit_file_fn should not be called for code={code!r}")


# ---------------------------------------------------------------------------
# Name-marker fast path (no holdings lookup)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["KODEX 인버스", "TIGER 미국나스닥100", "KODEX 국고채3년"],
)
def test_name_marker_fast_path_is_taxable_without_deposit_call(name):
    result = m.classify_etf_tax(
        "000001", deposit_file_fn=_NotCalled(), name_fn=lambda code: name
    )
    assert result == m.TAXABLE


def test_silver_marker_does_not_false_positive_on_bank_name():
    # "은" (silver) is a marker, but "은행" (bank) must not match it — must
    # fall through to the holdings path instead of being flagged blindly.
    calls = []

    def deposit_fn(code: str) -> pd.DataFrame:
        calls.append(code)
        return _deposit_df(["005930", "000660"])

    result = m.classify_etf_tax(
        "091170", deposit_file_fn=deposit_fn, name_fn=lambda code: "KODEX 은행"
    )
    assert result == m.DOMESTIC_EQUITY
    assert calls == ["091170"]


# ---------------------------------------------------------------------------
# Holdings path
# ---------------------------------------------------------------------------


def test_holdings_all_kr_codes_is_domestic_equity():
    result = m.classify_etf_tax(
        "091170",
        deposit_file_fn=lambda code: _deposit_df(["005930", "000660", "035420"]),
        name_fn=lambda code: "KODEX 은행",
    )
    assert result == m.DOMESTIC_EQUITY


def test_holdings_with_foreign_tickers_is_taxable():
    result = m.classify_etf_tax(
        "091170",
        deposit_file_fn=lambda code: _deposit_df(["005930", "AAPL", "MSFT", "GOOG"]),
        name_fn=lambda code: "KODEX 은행",
    )
    assert result == m.TAXABLE


def test_holdings_ratio_at_threshold_is_domestic_equity():
    # 8/10 = 0.8 -> meets the >= 0.8 threshold.
    tickers = [f"{i:06d}" for i in range(8)] + ["CASH", "ETC"]
    result = m.classify_etf_tax(
        "091170",
        deposit_file_fn=lambda code: _deposit_df(tickers),
        name_fn=lambda code: "KODEX 은행",
    )
    assert result == m.DOMESTIC_EQUITY


def test_holdings_ratio_below_threshold_is_taxable():
    # 5/10 = 0.5 -> below the >= 0.8 threshold.
    tickers = [f"{i:06d}" for i in range(5)] + [f"F{i}" for i in range(5)]
    result = m.classify_etf_tax(
        "091170",
        deposit_file_fn=lambda code: _deposit_df(tickers),
        name_fn=lambda code: "KODEX 은행",
    )
    assert result == m.TAXABLE


# ---------------------------------------------------------------------------
# Exception / empty holdings -> conservative taxable default
# ---------------------------------------------------------------------------


def test_deposit_file_exception_defaults_to_taxable():
    def raising_fn(code: str) -> pd.DataFrame:
        raise RuntimeError("KRX endpoint down")

    result = m.classify_etf_tax(
        "091170", deposit_file_fn=raising_fn, name_fn=lambda code: "KODEX 은행"
    )
    assert result == m.TAXABLE


def test_empty_holdings_defaults_to_taxable():
    result = m.classify_etf_tax(
        "091170",
        deposit_file_fn=lambda code: pd.DataFrame(),
        name_fn=lambda code: "KODEX 은행",
    )
    assert result == m.TAXABLE


def test_name_fn_exception_defaults_to_taxable_without_deposit_call():
    def raising_name_fn(code: str) -> str:
        raise RuntimeError("name lookup failed")

    result = m.classify_etf_tax(
        "091170", deposit_file_fn=_NotCalled(), name_fn=raising_name_fn
    )
    assert result == m.TAXABLE


# ---------------------------------------------------------------------------
# build_auto_tax_csv
# ---------------------------------------------------------------------------


def test_build_auto_tax_csv_writes_mixed_classes(tmp_path: Path):
    names = {
        "069500": "KODEX 200",
        "114800": "KODEX 인버스",
        "091170": "KODEX 은행",
    }
    holdings = {
        "069500": _deposit_df(["005930", "000660", "035420"]),
        "091170": _deposit_df(["005930", "000660"]),
    }

    out_path = tmp_path / "kr_etf_tax_class.auto.csv"
    counts = m.build_auto_tax_csv(
        list(names.keys()),
        out_path,
        deposit_file_fn=lambda code: holdings[code],
        name_fn=lambda code: names[code],
    )

    assert counts == {"domestic_equity": 2, "taxable": 1, "total": 3}
    assert out_path.exists()

    with out_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    by_code = {row["code"]: row for row in rows}
    assert by_code["069500"]["tax_class"] == "domestic_equity"
    assert by_code["069500"]["name"] == "KODEX 200"
    assert by_code["114800"]["tax_class"] == "taxable"
    assert by_code["091170"]["tax_class"] == "domestic_equity"
    assert [r["code"] for r in rows] == ["069500", "114800", "091170"]


def test_build_auto_tax_csv_creates_parent_dirs(tmp_path: Path):
    out_path = tmp_path / "nested" / "dir" / "auto.csv"
    counts = m.build_auto_tax_csv(
        ["114800"],
        out_path,
        deposit_file_fn=_NotCalled(),
        name_fn=lambda code: "KODEX 인버스",
    )
    assert counts == {"domestic_equity": 0, "taxable": 1, "total": 1}
    assert out_path.exists()
