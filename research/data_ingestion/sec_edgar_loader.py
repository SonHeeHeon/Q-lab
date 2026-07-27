"""SEC EDGAR XBRL fundamentals ingestion — replaces yfinance's shallow
(~6 quarter) US financials with point-in-time history back to ~2007.

Why: yfinance quarterly financials only expose the last ~6 quarters, which is
useless for multi-year Value/Quality backtesting. SEC's ``companyfacts`` API is
free/no-auth and returns every XBRL fact a company ever filed. One HTTP call per
company yields all concepts.

Point-in-time correctness (the whole point):
- ``fiscal_period`` = the quarter-end date the figure describes.
- ``disclosed_at`` = the SEC filing date (``filed``) — the day the number became
  public. Factors gate on ``disclosed_at <= as_of`` (see factors/value.py,
  factors/quality.py) so using the period-end here would leak the future.

Flows (revenue, income, cash flows) are stored as **discrete 3-month quarterly**
values. SEC 10-Qs report Q1/Q2/Q3; the 10-K reports the full year (no discrete
Q4), so Q4 is reconstructed as FY − (Q1+Q2+Q3). When a company only files
cumulative YTD figures, quarters are recovered by differencing consecutive YTD
points within the fiscal year. Balance-sheet items (assets, equity, shares) are
instantaneous — taken as-of each period-end.

Source: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json
SEC fair-access policy: descriptive User-Agent with contact + <=10 req/s.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import date

import certifi
import requests

from shared.db.session import research_db_path

# SEC requires a descriptive UA with a contact address (fair-access policy).
SEC_UA = "Q-Lab research (contact: sonny7.son@samsung.com)"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# financials_us column  ->  ordered us-gaap concept candidates (first hit wins).
# 'unit' picks which units block to read; 'kind' picks extraction (flow vs instant).
_DURATION_CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueGoodsNet",  # pre-ASC606 goods sellers (e.g. KO)
        "SalesRevenueServicesNet",
        "RevenuesNetOfInterestExpense",  # broker-dealers
    ],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "cfo": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "gross_profit": ["GrossProfit"],  # fallback = revenue - cost (below)
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "dividends_paid": [
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfDividends",
    ],
    "_cost_of_revenue": [  # only used to synthesize gross_profit when GrossProfit absent
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ],
}
_EPS_CONCEPTS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]  # unit USD/shares
_INSTANT_CONCEPTS: dict[str, list[str]] = {
    "total_assets": ["Assets"],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
}
# Shares outstanding — dei concept is a clean point-in-time count; us-gaap avg is fallback.
_SHARES_INSTANT = ("dei", ["EntityCommonStockSharesOutstanding"])
_SHARES_DURATION = [
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
]

_NEW_COLUMNS = ["cfo", "capex", "gross_profit", "buybacks", "dividends_paid", "shares_out"]


@dataclass
class LoadResult:
    name: str
    requested: int
    inserted_or_ignored: int


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"})
    s.verify = certifi.where()
    return s


def _get_json(session: requests.Session, url: str) -> dict:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def cik_map(session: requests.Session) -> dict[str, int]:
    """ticker (upper) -> integer CIK, from SEC's master list."""
    data = _get_json(session, TICKERS_URL)
    return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}


def _all_units(facts: dict, taxonomy: str, names: list[str], unit: str) -> list[list[dict]]:
    """Every concept in ``names`` that exists, in priority order → list of unit
    arrays. Companies switch tags over time (e.g. ASC 606 in 2018 moved everyone
    from ``SalesRevenueNet``/``Revenues`` to ``RevenueFromContractWithCustomer…``),
    so a single concept covers only one era. Merging candidates fills the gap."""
    block = facts.get("facts", {}).get(taxonomy, {})
    result = []
    for name in names:
        concept = block.get(name)
        if concept and unit in concept.get("units", {}):
            result.append(concept["units"][unit])
    return result


def _merged_quarterly(
    facts: dict, taxonomy: str, names: list[str], unit: str
) -> dict[str, tuple[float, str]]:
    """Quarterly flows merged across candidate concepts; higher-priority concept
    wins per period-end, lower-priority ones only fill periods it lacks."""
    merged: dict[str, tuple[float, str]] = {}
    for units in _all_units(facts, taxonomy, names, unit):
        for end, vf in _duration_quarterly(units).items():
            merged.setdefault(end, vf)
    return merged


def _merged_instant(
    facts: dict, taxonomy: str, names: list[str], unit: str
) -> dict[str, tuple[float, str]]:
    """Instant values merged across candidate concepts (priority fill)."""
    merged: dict[str, tuple[float, str]] = {}
    for units in _all_units(facts, taxonomy, names, unit):
        for end, vf in _instant_series(units).items():
            merged.setdefault(end, vf)
    return merged


def _duration_quarterly(units: list[dict]) -> dict[str, tuple[float, str]]:
    """Discrete 3-month values keyed by period-end (ISO). Reconstructs quarters
    from cumulative YTD figures when discrete ones are missing.

    Returns {end_date: (value, filed_date)}.
    """
    # Group durations by fiscal year, keeping discrete (~3M) and cumulative (YTD).
    by_fy: dict[int, dict] = {}
    for u in units:
        if "start" not in u or "end" not in u or u.get("val") is None:
            continue
        try:
            start = date.fromisoformat(u["start"])
            end = date.fromisoformat(u["end"])
        except ValueError:
            continue
        length = (end - start).days
        if length < 20 or length > 380:  # ignore odd/partial windows
            continue
        fy = u.get("fy")
        fp = u.get("fp")
        if fy is None or fp is None:
            continue
        slot = by_fy.setdefault(int(fy), {})
        entry = {"end": end, "start": start, "val": float(u["val"]), "filed": u["filed"]}
        if 80 <= length <= 100:
            slot.setdefault("discrete", {})[fp] = entry
        else:
            # cumulative YTD; keep the longest window per fp (the true YTD)
            cur = slot.setdefault("cumulative", {}).get(fp)
            if cur is None or length > (cur["end"] - cur["start"]).days:
                slot["cumulative"][fp] = entry

    out: dict[str, tuple[float, str]] = {}
    order = ["Q1", "Q2", "Q3", "Q4", "FY"]
    for fy, slot in by_fy.items():
        discrete = slot.get("discrete", {})
        cumulative = slot.get("cumulative", {})
        running = 0.0  # sum of quarters already booked this fiscal year
        for fp in order:
            d = discrete.get(fp)
            if d is not None:  # discrete 3-month reported directly
                out[d["end"].isoformat()] = (d["val"], d["filed"])
                running += d["val"]
                continue
            c = cumulative.get(fp)
            if c is None:
                continue
            # Don't overwrite a discrete Q4 with the FY residual (same year-end).
            if c["end"].isoformat() in out:
                continue
            # quarter = cumulative(YTD or full year) minus what's already booked.
            q_val = c["val"] - running
            out[c["end"].isoformat()] = (q_val, c["filed"])
            running += q_val
    return out


def _instant_series(units: list[dict]) -> dict[str, tuple[float, str]]:
    """Point-in-time values keyed by period-end (ISO): {end: (value, filed)}.
    When multiple filings report the same end, keep the earliest disclosure."""
    out: dict[str, tuple[float, str]] = {}
    for u in units:
        if u.get("val") is None or "end" not in u:
            continue
        end = u["end"]
        filed = u["filed"]
        cur = out.get(end)
        if cur is None or filed < cur[1]:
            out[end] = (float(u["val"]), filed)
    return out


def _asof(series: dict[str, tuple[float, str]], period_end: str) -> tuple[float, str] | None:
    """Latest instant value whose end <= period_end (dei shares are tagged on the
    cover date, not the quarter-end, so exact-date matching misses them)."""
    best = None
    for end, vf in series.items():
        if end <= period_end and (best is None or end > best[0]):
            best = (end, vf)
    return best[1] if best else None


def extract_financials(ticker: str, facts: dict) -> list[dict]:
    """Assemble per-quarter financials_us rows from a companyfacts payload."""
    dur: dict[str, dict[str, tuple[float, str]]] = {}
    for col, names in _DURATION_CONCEPTS.items():
        dur[col] = _merged_quarterly(facts, "us-gaap", names, "USD")
    eps = _merged_quarterly(facts, "us-gaap", _EPS_CONCEPTS, "USD/shares")

    inst: dict[str, dict[str, tuple[float, str]]] = {}
    for col, names in _INSTANT_CONCEPTS.items():
        inst[col] = _merged_instant(facts, "us-gaap", names, "USD")
    # shares: prefer dei instant count, fall back to us-gaap weighted-average duration
    shares = _merged_instant(facts, _SHARES_INSTANT[0], _SHARES_INSTANT[1], "shares")
    if not shares:
        shares = _merged_quarterly(facts, "us-gaap", _SHARES_DURATION, "shares")

    # Synthesize gross_profit = revenue - cost when GrossProfit wasn't tagged.
    if not dur.get("gross_profit"):
        gp: dict[str, tuple[float, str]] = {}
        cost = dur.get("_cost_of_revenue", {})
        for end, (rev, filed) in dur.get("revenue", {}).items():
            if end in cost:
                gp[end] = (rev - cost[end][0], max(filed, cost[end][1]))
        dur["gross_profit"] = gp
    dur.pop("_cost_of_revenue", None)

    # Union of all quarter-end dates that carry an income figure.
    period_ends = set(dur.get("net_income", {})) | set(dur.get("revenue", {}))
    rows: list[dict] = []
    for end in sorted(period_ends):
        row: dict = {"ticker": ticker, "fiscal_period": end}
        disclosed: list[str] = []
        for col in ("revenue", "operating_income", "net_income", "cfo", "capex",
                    "gross_profit", "buybacks", "dividends_paid"):
            v = dur.get(col, {}).get(end)
            row[col] = v[0] if v else None
            if v:
                disclosed.append(v[1])
        e = eps.get(end)
        row["eps"] = e[0] if e else None
        if e:
            disclosed.append(e[1])
        for col in ("total_assets", "total_equity"):
            v = inst.get(col, {}).get(end)
            row[col] = v[0] if v else None
            if v:
                disclosed.append(v[1])
        sh = _asof(shares, end)  # dei shares are off-cycle → as-of, not exact match
        row["shares_out"] = sh[0] if sh else None
        if sh:
            disclosed.append(sh[1])
        # bps = equity / shares (value.py fills it this way too; precompute when possible)
        row["bps"] = (
            row["total_equity"] / row["shares_out"]
            if row.get("total_equity") and row.get("shares_out")
            else None
        )
        if not disclosed:
            continue  # no public figure for this period -> skip (never fabricate a date)
        # Row is only fully public once its LAST piece was filed → conservative, no look-ahead.
        row["disclosed_at"] = max(disclosed)
        rows.append(row)
    return rows


def _ensure_financials_us_columns(conn: sqlite3.Connection) -> None:
    """Add v2 factor columns to the ad-hoc financials_us table (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS financials_us (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            fiscal_period DATE NOT NULL,
            disclosed_at DATE NOT NULL,
            revenue NUMERIC, operating_income NUMERIC, net_income NUMERIC,
            total_assets NUMERIC, total_equity NUMERIC, eps NUMERIC, bps NUMERIC,
            currency TEXT NOT NULL DEFAULT 'USD',
            UNIQUE (ticker, fiscal_period)
        )
        """
    )
    existing = {r[1] for r in conn.execute("PRAGMA table_info(financials_us)")}
    for col in _NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE financials_us ADD COLUMN {col} NUMERIC")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_financials_us_ticker_disclosed"
        " ON financials_us (ticker, disclosed_at)"
    )


_INSERT_COLUMNS = [
    "ticker", "fiscal_period", "disclosed_at", "revenue", "operating_income",
    "net_income", "total_assets", "total_equity", "eps", "bps",
    "cfo", "capex", "gross_profit", "buybacks", "dividends_paid", "shares_out",
]


def _upsert(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
    updates = ", ".join(
        f"{c} = excluded.{c}" for c in _INSERT_COLUMNS if c not in ("ticker", "fiscal_period")
    )
    conn.executemany(
        f"INSERT INTO financials_us ({', '.join(_INSERT_COLUMNS)}, currency)"
        f" VALUES ({placeholders}, 'USD')"
        f" ON CONFLICT(ticker, fiscal_period) DO UPDATE SET {updates}, currency = 'USD'",
        [tuple(r.get(c) for c in _INSERT_COLUMNS) for r in rows],
    )
    return len(rows)


def update_us_financials_edgar(
    *,
    tickers: list[str] | None = None,
    db_path=None,
    sleep_seconds: float = 0.12,  # ponytail: single-thread <=10 req/s honors SEC fair-access
    limit: int | None = None,
) -> LoadResult:
    """Ingest SEC EDGAR fundamentals for ``tickers`` (default: all non-ETF stocks_us)."""
    path = str(db_path or research_db_path)
    session = _session()
    with sqlite3.connect(path) as conn:
        _ensure_financials_us_columns(conn)
        if tickers is None:
            tickers = [
                r[0]
                for r in conn.execute(
                    "SELECT ticker FROM stocks_us WHERE exchange != 'ETF' AND is_delisted = 0"
                    " ORDER BY ticker"
                )
            ]
        if limit:
            tickers = tickers[:limit]
        ciks = cik_map(session)
        requested = inserted = missing_cik = failed = 0
        for i, ticker in enumerate(tickers):
            cik = ciks.get(ticker.upper())
            if cik is None:
                missing_cik += 1
                continue
            try:
                facts = _get_json(session, FACTS_URL.format(cik=cik))
                if "us-gaap" not in facts.get("facts", {}):
                    # SEC throttling can return a 200 without the facts block;
                    # one paced retry recovers it rather than silently skipping.
                    time.sleep(1.0)
                    facts = _get_json(session, FACTS_URL.format(cik=cik))
            except Exception as exc:  # noqa: BLE001 - network is best-effort per company
                failed += 1
                print(f"[edgar:warn] {ticker} (CIK {cik}) failed: {exc}")
                time.sleep(sleep_seconds)
                continue
            rows = extract_financials(ticker, facts)
            requested += len(rows)
            inserted += _upsert(conn, rows)
            conn.commit()
            if i % 25 == 0:
                print(f"[edgar] {i + 1}/{len(tickers)} {ticker}: {len(rows)} periods")
            time.sleep(sleep_seconds)
    print(
        f"[edgar] done: {inserted} rows, missing_cik={missing_cik}, failed={failed}"
    )
    return LoadResult(name="edgar_financials", requested=requested, inserted_or_ignored=inserted)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Ingest SEC EDGAR fundamentals into financials_us")
    ap.add_argument("--limit", type=int, default=None, help="cap number of tickers (smoke test)")
    ap.add_argument("--ticker", action="append", help="specific ticker(s) instead of full universe")
    args = ap.parse_args()
    result = update_us_financials_edgar(tickers=args.ticker, limit=args.limit)
    print(result)
