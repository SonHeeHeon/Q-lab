"""KOSPI200 constituent resolver with offline-friendly fallbacks."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from io import StringIO
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from shared.db.session import research_db_path

os.environ.setdefault("MPLCONFIGDIR", str(Path("/private/tmp/qlab-mplconfig")))


def _bootstrap_ssl_certificates() -> None:
    """Make urllib-based fallback sources use certifi when system CA is missing."""

    try:
        import certifi
    except Exception:
        return

    ca_file = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", ca_file)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_file)


_bootstrap_ssl_certificates()

KOSPI200_INDEX_CODE = "1028"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "universe"
DEFAULT_CODES_FILE = PROJECT_ROOT / "data" / "manual" / "kospi200_codes.csv"
MIN_DB_FALLBACK_CODES = 50
MIN_REFRESH_CODES = 180


@dataclass(frozen=True, slots=True)
class ResolvedKOSPI200:
    as_of: date
    source: str
    codes: list[str]


@dataclass(frozen=True, slots=True)
class KOSPI200RefreshResult:
    as_of: date
    source: str
    path: Path
    previous_count: int
    current_count: int
    added: list[str]
    removed: list[str]
    updated: bool


def get_kospi200(as_of: date | str, *, allow_fallback: bool = True) -> list[str]:
    """Return KOSPI200 constituent stock codes as of a given date.

    pykrx occasionally receives empty or malformed responses from KRX's index
    constituent endpoint. For overnight data jobs we prefer a clearly logged
    approximation over stopping the entire pipeline before price collection can
    even begin.
    """

    return resolve_kospi200(as_of, allow_fallback=allow_fallback).codes


def resolve_kospi200(
    as_of: date | str,
    *,
    allow_fallback: bool = True,
    prefer_cache: bool = True,
    include_manual_file: bool = True,
) -> ResolvedKOSPI200:
    """Resolve KOSPI200 codes and retain the source used."""

    resolved_date = _to_date(as_of)
    date_text = _to_yyyymmdd(as_of)

    codes = _from_pykrx_index(date_text)
    if codes:
        _write_cache(date_text, codes, source="krx_index")
        return ResolvedKOSPI200(
            as_of=resolved_date,
            source="pykrx:krx_index",
            codes=codes,
        )

    if not allow_fallback:
        return ResolvedKOSPI200(
            as_of=resolved_date,
            source="none",
            codes=[],
        )

    if prefer_cache and (cached := _read_exact_cache(date_text)):
        print(
            "[phase2:warn] using cached KOSPI200 constituents for "
            f"{date_text}: {len(cached)} codes"
        )
        return ResolvedKOSPI200(
            as_of=resolved_date,
            source="cache:exact_date",
            codes=cached,
        )

    codes = _from_fdr_index_snapshot()
    if codes:
        print(
            "[phase2:warn] using FinanceDataReader KRX index snapshot "
            f"fallback: {len(codes)} codes"
        )
        _write_cache(date_text, codes, source="fdr_krx_index_snapshot")
        return ResolvedKOSPI200(
            as_of=resolved_date,
            source="fdr:krx_index_snapshot",
            codes=codes,
        )

    codes = _from_wikipedia_components()
    if codes:
        print(
            "[phase2:warn] using Wikipedia KOSPI200 components fallback: "
            f"{len(codes)} codes"
        )
        _write_cache(date_text, codes, source="wikipedia_components")
        return ResolvedKOSPI200(
            as_of=resolved_date,
            source="wikipedia:components",
            codes=codes,
        )

    codes = _approximate_top_kospi_by_size(date_text, limit=200)
    if codes:
        print(
            "[phase2:warn] using approximate KOSPI200 fallback: "
            f"top {len(codes)} KOSPI stocks by market cap/current listing"
        )
        _write_cache(date_text, codes, source="approx_top_kospi")
        return ResolvedKOSPI200(
            as_of=resolved_date,
            source="approx:top_kospi_by_size",
            codes=codes,
        )

    cached = _read_latest_cache()
    if cached:
        print(
            "[phase2:warn] using latest cached KOSPI200 constituents: "
            f"{len(cached)} codes"
        )
        return ResolvedKOSPI200(
            as_of=resolved_date,
            source="cache:latest",
            codes=cached,
        )

    if include_manual_file:
        manual_codes = _from_manual_codes_file(minimum=MIN_DB_FALLBACK_CODES)
        if manual_codes:
            print(
                "[phase2:warn] using manual KOSPI200 codes file fallback: "
                f"{len(manual_codes)} codes"
            )
            return ResolvedKOSPI200(
                as_of=resolved_date,
                source="manual:kospi200_codes_file",
                codes=manual_codes,
            )

    db_codes = _from_research_db(_to_date(as_of), minimum=MIN_DB_FALLBACK_CODES)
    if db_codes:
        print(
            "[phase2:warn] using research.db KOSPI stock fallback: "
            f"{len(db_codes)} codes"
        )
        return ResolvedKOSPI200(
            as_of=resolved_date,
            source="research_db:kospi_stocks",
            codes=db_codes,
        )

    return ResolvedKOSPI200(
        as_of=resolved_date,
        source="none",
        codes=[],
    )


def refresh_kospi200_codes_file(
    *,
    as_of: date | str | None = None,
    path: Path = DEFAULT_CODES_FILE,
    min_codes: int = MIN_REFRESH_CODES,
) -> KOSPI200RefreshResult:
    """Fetch the latest KOSPI200 list and update the manual CSV when changed."""

    resolved = resolve_kospi200(
        as_of or date.today(),
        allow_fallback=True,
        prefer_cache=False,
        include_manual_file=False,
    )
    if len(resolved.codes) < min_codes:
        raise RuntimeError(
            "KOSPI200 refresh resolved too few codes: "
            f"{len(resolved.codes)} from {resolved.source}. "
            "Refusing to overwrite the manual universe file."
        )

    target = path if path.is_absolute() else PROJECT_ROOT / path
    previous = _read_codes_file(target)
    previous_set = set(previous)
    current_set = set(resolved.codes)
    added = sorted(current_set - previous_set)
    removed = sorted(previous_set - current_set)
    updated = added != [] or removed != [] or previous != resolved.codes

    if updated:
        _write_codes_file(target, resolved.codes, as_of=resolved.as_of, source=resolved.source)

    return KOSPI200RefreshResult(
        as_of=resolved.as_of,
        source=resolved.source,
        path=target,
        previous_count=len(previous),
        current_count=len(resolved.codes),
        added=added,
        removed=removed,
        updated=updated,
    )


def _from_pykrx_index(date_text: str) -> list[str]:
    """Fetch official KOSPI200 constituents from pykrx/KRX."""

    from pykrx import stock

    try:
        codes = stock.get_index_portfolio_deposit_file(
            KOSPI200_INDEX_CODE,
            date_text,
            alternative=True,
        )
    except Exception as exc:
        print(f"[phase2:warn] KOSPI200 constituent lookup failed: {exc}")
        return []
    return sorted({str(code).zfill(6) for code in codes})


def _from_fdr_index_snapshot() -> list[str]:
    """Fetch KOSPI200 constituents through FinanceDataReader's KRX snapshot path."""

    try:
        import FinanceDataReader as fdr

        frame = fdr.SnapDataReader(f"KRX/INDEX/STOCK/{KOSPI200_INDEX_CODE}")
    except Exception as exc:
        print(f"[phase2:warn] FinanceDataReader KOSPI200 snapshot failed: {exc}")
        return []

    if frame is None or frame.empty:
        return []

    code_col = _first_existing_column(
        frame,
        "Code",
        "ISU_SRT_CD",
        "short_code",
        "종목코드",
    )
    if code_col is None:
        return _normalize_codes(frame.index)
    return _normalize_codes(frame[code_col].tolist())


def _from_wikipedia_components() -> list[str]:
    """Fetch the public KOSPI 200 component table from Wikipedia."""

    url = "https://en.wikipedia.org/wiki/KOSPI_200"
    try:
        import certifi
        import requests

        response = requests.get(
            url,
            headers={"User-Agent": "Q-Lab/1.0 KOSPI200 updater"},
            timeout=15,
            verify=certifi.where(),
        )
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
    except Exception as exc:
        print(f"[phase2:warn] Wikipedia KOSPI200 fallback failed: {exc}")
        return []

    for table in tables:
        if table.empty:
            continue
        columns = [str(column).strip().lower() for column in table.columns]
        if "symbol" not in columns:
            continue
        symbol_col = table.columns[columns.index("symbol")]
        codes = _normalize_codes(table[symbol_col].tolist())
        if len(codes) >= MIN_DB_FALLBACK_CODES:
            return codes
    return []


async def get_kospi200_async(as_of: date | str) -> list[str]:
    import asyncio

    return await asyncio.to_thread(get_kospi200, as_of)


def _approximate_top_kospi_by_size(date_text: str, *, limit: int) -> list[str]:
    """Approximate KOSPI200 using current KOSPI market-cap ranking."""

    codes = _top_kospi_by_pykrx_market_cap(date_text, limit=limit)
    if codes:
        return codes

    codes = _top_kospi_by_fdr_listing(limit=limit)
    if codes:
        return codes

    codes = _kospi_ticker_list_by_pykrx(date_text, limit=limit)
    if codes:
        print(
            "[phase2:warn] market-cap ranking unavailable; "
            "falling back to first KOSPI ticker-list codes"
        )
        return codes

    return []


def _top_kospi_by_pykrx_market_cap(date_text: str, *, limit: int) -> list[str]:
    from pykrx import stock

    for candidate in _date_candidates(date_text):
        try:
            frame = stock.get_market_cap_by_ticker(candidate, market="KOSPI")
        except Exception as exc:
            print(f"[phase2:warn] pykrx market-cap fallback failed: {exc}")
            return []
        if frame is None or frame.empty or "시가총액" not in frame.columns:
            continue
        frame = frame.sort_values("시가총액", ascending=False)
        return _normalize_codes(frame.index)[:limit]
    return []


def _top_kospi_by_fdr_listing(*, limit: int) -> list[str]:
    try:
        import FinanceDataReader as fdr
    except Exception as exc:
        print(f"[phase2:warn] FinanceDataReader import failed: {exc}")
        return []

    try:
        frame = fdr.StockListing("KOSPI")
    except Exception as exc:
        print(f"[phase2:warn] FinanceDataReader KOSPI listing failed: {exc}")
        try:
            frame = fdr.StockListing("KRX")
        except Exception as fallback_exc:
            print(f"[phase2:warn] FinanceDataReader KRX listing failed: {fallback_exc}")
            return []

    if frame is None or frame.empty:
        return []

    if "Market" in frame.columns:
        frame = frame[frame["Market"].astype(str).str.upper().eq("KOSPI")]

    code_col = _first_existing_column(frame, "Code", "Symbol", "종목코드")
    if code_col is None:
        return []

    size_col = _first_existing_column(
        frame,
        "Marcap",
        "MarketCap",
        "Market Cap",
        "시가총액",
    )
    if size_col is not None:
        frame = frame.copy()
        frame[size_col] = pd.to_numeric(frame[size_col], errors="coerce")
        frame = frame.sort_values(size_col, ascending=False)

    return _normalize_codes(frame[code_col].tolist())[:limit]


def _kospi_ticker_list_by_pykrx(date_text: str, *, limit: int) -> list[str]:
    from pykrx import stock

    for candidate in _date_candidates(date_text):
        try:
            codes = stock.get_market_ticker_list(candidate, "KOSPI")
        except Exception as exc:
            print(f"[phase2:warn] pykrx KOSPI ticker fallback failed: {exc}")
            return []
        normalized = _normalize_codes(codes)
        if normalized:
            return normalized[:limit]
    return []


def _from_research_db(as_of: date, *, minimum: int) -> list[str]:
    sql = """
        SELECT code
        FROM stocks
        WHERE market = 'KOSPI'
          AND listed_at <= ?
          AND (delisted_at IS NULL OR delisted_at > ?)
        ORDER BY code
    """
    try:
        with sqlite3.connect(research_db_path) as conn:
            rows = conn.execute(sql, [as_of.isoformat(), as_of.isoformat()]).fetchall()
    except sqlite3.Error:
        return []
    codes = _normalize_codes(row[0] for row in rows)
    if len(codes) < minimum:
        if codes:
            print(
                "[phase2:warn] research.db KOSPI fallback has only "
                f"{len(codes)} codes; refusing to treat it as a full universe"
            )
        return []
    return codes


def _from_manual_codes_file(*, minimum: int) -> list[str]:
    codes = _read_codes_file(DEFAULT_CODES_FILE)
    if len(codes) < minimum:
        return []
    return codes


def _write_cache(date_text: str, codes: list[str], *, source: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"as_of": date_text, "source": source, "codes": codes}
        (CACHE_DIR / f"kospi200_{date_text}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


def _read_exact_cache(date_text: str) -> list[str]:
    return _read_cache_file(CACHE_DIR / f"kospi200_{date_text}.json")


def _read_latest_cache() -> list[str]:
    try:
        paths = sorted(CACHE_DIR.glob("kospi200_*.json"), reverse=True)
    except OSError:
        return []
    for path in paths:
        codes = _read_cache_file(path)
        if codes:
            return codes
    return []


def _read_cache_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    codes = payload.get("codes")
    if not isinstance(codes, list):
        return []
    return _normalize_codes(codes)


def _read_codes_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    return list(dict.fromkeys(re.findall(r"(?<!\d)\d{6}(?!\d)", text)))


def _write_codes_file(
    path: Path,
    codes: list[str],
    *,
    as_of: date,
    source: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# KOSPI200 manual universe fallback",
        "# Auto-updated by /api/settings/universe/kospi200/refresh.",
        f"# as_of={as_of.isoformat()}",
        f"# source={source}",
        "",
        *codes,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _date_candidates(date_text: str, *, lookback_days: int = 10) -> list[str]:
    base = _to_date(date_text)
    return [
        date.fromordinal(base.toordinal() - offset).strftime("%Y%m%d")
        for offset in range(lookback_days + 1)
    ]


def _first_existing_column(frame: pd.DataFrame, *names: str) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _normalize_codes(codes: object) -> list[str]:
    normalized: list[str] = []
    for code in codes:
        value = str(code).strip().split(".")[0].zfill(6)
        if value.isdigit() and len(value) == 6:
            normalized.append(value)
    return list(dict.fromkeys(normalized))


def _to_yyyymmdd(value: date | str) -> str:
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    return value.replace("-", "")


def _to_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    text = value.replace("-", "")
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
