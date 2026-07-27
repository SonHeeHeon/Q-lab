"""SEC EDGAR loader — offline correctness (no network).

Guards the two things that make or break point-in-time backtesting:
1. quarterly reconstruction (discrete 3M, Q4 = FY - Q1..Q3, YTD differencing)
2. disclosed_at = filing date, always on/after period end (no look-ahead)
"""

from __future__ import annotations

from research.data_ingestion.sec_edgar_loader import extract_financials


def _usd(start, end, val, filed, fy, fp):
    return {"start": start, "end": end, "val": val, "filed": filed, "fy": fy, "fp": fp}


def _instant(end, val, filed):
    return {"end": end, "val": val, "filed": filed, "fy": 0, "fp": "FY"}


# NetIncomeLoss: Q1/Q2/Q3 discrete 3-month + FY annual (no discrete Q4).
# CFO: Q1 discrete + Q2/Q3/FY cumulative YTD (differencing path).
FACTS = {
    "facts": {
        "us-gaap": {
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        _usd("2022-01-01", "2022-03-31", 100, "2022-04-20", 2022, "Q1"),
                        _usd("2022-04-01", "2022-06-30", 110, "2022-07-20", 2022, "Q2"),
                        _usd("2022-07-01", "2022-09-30", 120, "2022-10-20", 2022, "Q3"),
                        _usd("2022-01-01", "2022-12-31", 500, "2023-02-15", 2022, "FY"),
                    ]
                }
            },
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {
                    "USD": [
                        _usd("2022-01-01", "2022-03-31", 50, "2022-04-20", 2022, "Q1"),
                        _usd("2022-01-01", "2022-06-30", 130, "2022-07-20", 2022, "Q2"),
                        _usd("2022-01-01", "2022-09-30", 200, "2022-10-20", 2022, "Q3"),
                        _usd("2022-01-01", "2022-12-31", 300, "2023-02-15", 2022, "FY"),
                    ]
                }
            },
            "Assets": {
                "units": {
                    "USD": [
                        _instant("2022-03-31", 1000, "2022-04-20"),
                        _instant("2022-12-31", 1200, "2023-02-15"),
                    ]
                }
            },
            "StockholdersEquity": {
                "units": {"USD": [_instant("2022-12-31", 600, "2023-02-15")]}
            },
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {"shares": [_instant("2022-12-31", 300, "2023-02-15")]}
            }
        },
    }
}


def _by_period(rows):
    return {r["fiscal_period"]: r for r in rows}


def test_quarterly_reconstruction_and_ytd_differencing():
    rows = _by_period(extract_financials("FOO", FACTS))
    # discrete quarters kept verbatim
    assert rows["2022-03-31"]["net_income"] == 100
    assert rows["2022-06-30"]["net_income"] == 110
    assert rows["2022-09-30"]["net_income"] == 120
    # Q4 reconstructed = FY(500) - (100+110+120) = 170
    assert rows["2022-12-31"]["net_income"] == 170
    # CFO: Q1 discrete 50, then YTD differencing 130-50=80, 200-130=70, 300-200=100
    assert rows["2022-03-31"]["cfo"] == 50
    assert rows["2022-06-30"]["cfo"] == 80
    assert rows["2022-09-30"]["cfo"] == 70
    assert rows["2022-12-31"]["cfo"] == 100


def test_disclosed_at_is_filing_date_never_before_period_end():
    rows = extract_financials("FOO", FACTS)
    for r in rows:
        # look-ahead guard: a figure is never usable before it was filed,
        # and a filing never predates the period it reports.
        assert r["disclosed_at"] >= r["fiscal_period"], r
    by = _by_period(rows)
    # Q1 became public on the 10-Q filing date, not the quarter-end.
    assert by["2022-03-31"]["disclosed_at"] == "2022-04-20"
    # Reconstructed Q4 is only public once the 10-K was filed.
    assert by["2022-12-31"]["disclosed_at"] == "2023-02-15"


def test_instant_items_are_point_in_time_and_bps_computed():
    by = _by_period(extract_financials("FOO", FACTS))
    assert by["2022-03-31"]["total_assets"] == 1000
    assert by["2022-12-31"]["total_assets"] == 1200
    # bps = equity / shares = 600 / 300 = 2.0
    assert by["2022-12-31"]["total_equity"] == 600
    assert by["2022-12-31"]["shares_out"] == 300
    assert by["2022-12-31"]["bps"] == 2.0
