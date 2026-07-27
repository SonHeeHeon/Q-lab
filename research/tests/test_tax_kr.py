"""KR tax classification module tests (research/backtest/tax_kr.py)."""

from __future__ import annotations

import csv

import pytest

from research.backtest import tax_kr


@pytest.fixture(autouse=True)
def _reset_tax_class_cache(monkeypatch):
    # The module caches the CSV lazily at module scope; reset it per-test so
    # tests that swap TAX_CLASS_FILE don't leak state into each other.
    monkeypatch.setattr(tax_kr, "_tax_class_cache", None)
    yield


CSV_CODES = {
    "069500": "etf_domestic_equity",
    "091160": "etf_domestic_equity",
    "229200": "etf_domestic_equity",
    "114260": "etf_taxable",
    "148070": "etf_taxable",
    "114800": "etf_taxable",
    "132030": "etf_taxable",
    "133690": "etf_taxable",
    "143850": "etf_taxable",
    "261240": "etf_taxable",
    "091170": "etf_domestic_equity",
    "091180": "etf_domestic_equity",
    "305720": "etf_domestic_equity",
    "266420": "etf_domestic_equity",
    "279530": "etf_domestic_equity",
    "360750": "etf_taxable",
    "381180": "etf_taxable",
    "192090": "etf_taxable",
    "251350": "etf_taxable",
    "195980": "etf_taxable",
    "245710": "etf_taxable",
    "144600": "etf_taxable",
    "130680": "etf_taxable",
    "153130": "etf_taxable",
    "273130": "etf_taxable",
    "305080": "etf_taxable",
    "329200": "etf_taxable",
    "458730": "etf_taxable",
    "329750": "etf_taxable",
}


@pytest.mark.parametrize("code,expected", list(CSV_CODES.items()))
def test_classify_all_csv_codes(code, expected):
    assert tax_kr.classify_kr_instrument(code) == expected


def test_classify_unlisted_6digit_code_is_stock():
    assert tax_kr.classify_kr_instrument("005930") == "stock"


def test_classify_unlisted_etf_is_unknown_not_stock():
    # Caller knows it's an ETF but the CSV doesn't list it -> must never be
    # silently taxed like a stock.
    assert tax_kr.classify_kr_instrument("005930", is_etf=True) == "unknown"


def test_classify_non_digit_ticker_is_unknown():
    assert tax_kr.classify_kr_instrument("AAPL") == "unknown"


def test_estimate_sell_tax_stock():
    result = tax_kr.estimate_sell_tax("005930", 10, 70_000.0, 60_000.0)
    assert result["tax_type"] == "stock"
    assert result["est_sell_tax"] == pytest.approx(
        10 * 70_000.0 * tax_kr.KR_STOCK_SELL_TAX_RATE
    )
    assert result["est_gains_tax"] == 0.0
    assert "비과세" in result["tax_note"]


def test_estimate_sell_tax_etf_domestic_equity():
    result = tax_kr.estimate_sell_tax("069500", 10, 30_000.0, 25_000.0)
    assert result["tax_type"] == "etf_domestic_equity"
    assert result["est_sell_tax"] == 0.0
    assert result["est_gains_tax"] == 0.0
    assert "비과세" in result["tax_note"]


def test_estimate_sell_tax_etf_taxable_positive_gain():
    result = tax_kr.estimate_sell_tax("114800", 10, 12_000.0, 10_000.0)
    assert result["tax_type"] == "etf_taxable"
    assert result["est_sell_tax"] == 0.0
    expected_gain_tax = tax_kr.ETF_TAXABLE_GAINS_RATE * (12_000.0 - 10_000.0) * 10
    assert result["est_gains_tax"] == pytest.approx(expected_gain_tax)
    assert "근사" in result["tax_note"]


def test_estimate_sell_tax_etf_taxable_negative_gain_is_zero():
    result = tax_kr.estimate_sell_tax("114800", 10, 8_000.0, 10_000.0)
    assert result["tax_type"] == "etf_taxable"
    assert result["est_gains_tax"] == 0.0


def test_estimate_sell_tax_unknown():
    result = tax_kr.estimate_sell_tax("AAPL", 10, 100.0, 90.0)
    assert result["tax_type"] == "unknown"
    assert result["est_sell_tax"] == 0.0
    assert result["est_gains_tax"] == 0.0
    assert "미등록" in result["tax_note"]


def test_missing_csv_file_tolerated(monkeypatch, tmp_path):
    monkeypatch.setattr(tax_kr, "TAX_CLASS_FILE", tmp_path / "does_not_exist.csv")
    # No file present -> empty mapping, tolerated (no exception), falls back
    # to default classification instead of crashing.
    assert tax_kr.classify_kr_instrument("069500") == "stock"
    assert tax_kr.classify_kr_instrument("005930") == "stock"


def test_merge_manual_wins_over_auto(monkeypatch, tmp_path):
    auto_file = tmp_path / "kr_etf_tax_class.auto.csv"
    auto_file.write_text(
        "code,tax_class,name\n069500,taxable,KODEX 200 (auto, wrong)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tax_kr, "AUTO_TAX_CLASS_FILE", auto_file)
    # Real manual TAX_CLASS_FILE classifies 069500 as domestic_equity; the
    # conflicting auto entry must lose to the manual one on merge.
    assert tax_kr.classify_kr_instrument("069500") == "etf_domestic_equity"


def test_merge_auto_only_code_is_used(monkeypatch, tmp_path):
    auto_file = tmp_path / "kr_etf_tax_class.auto.csv"
    auto_file.write_text(
        "code,tax_class,name\n999000,taxable,Auto-only ETF\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tax_kr, "AUTO_TAX_CLASS_FILE", auto_file)
    # 999000 isn't in the manual CSV -> the auto-only entry is used as-is.
    assert tax_kr.classify_kr_instrument("999000") == "etf_taxable"


def test_kr_etf_universe_has_29_rows_with_us_stability_etfs():
    universe_file = tax_kr.PROJECT_ROOT / "data" / "manual" / "kr_etf_universe.csv"
    with universe_file.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(
            line for line in fh if line.strip() and not line.lstrip().startswith("#")
        )
        rows = list(reader)
    assert len(rows) == 29
    codes = {row["code"] for row in rows}
    assert "458730" in codes  # TIGER 미국배당다우존스 (us_dividend)
    assert "329750" in codes  # TIGER 미국달러단기채권액티브 (us_bond_short)


def test_missing_auto_csv_tolerated(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tax_kr, "AUTO_TAX_CLASS_FILE", tmp_path / "does_not_exist.auto.csv"
    )
    # Auto CSV absent -> merge falls back to manual-only, no exception, and
    # manual-registered codes still classify correctly.
    assert tax_kr.classify_kr_instrument("069500") == "etf_domestic_equity"
    assert tax_kr.classify_kr_instrument("114800") == "etf_taxable"
