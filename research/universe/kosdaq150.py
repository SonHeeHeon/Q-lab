"""KOSDAQ150 constituent resolver with offline-friendly fallbacks."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from research.universe.kospi200 import (
    CACHE_DIR,
    MIN_DB_FALLBACK_CODES,
    PROJECT_ROOT,
    _date_candidates,
    _first_existing_column,
    _normalize_codes,
    _read_cache_file,
    _read_codes_file,
    _to_date,
    _to_yyyymmdd,
)
from shared.db.session import research_db_path

KOSDAQ150_INDEX_CODE = "2203"
KOSDAQ150_CODES_FILE = PROJECT_ROOT / "data" / "manual" / "kosdaq150_codes.csv"
MIN_REFRESH_CODES = 130


@dataclass(frozen=True, slots=True)
class ResolvedKOSDAQ150:
    as_of: date
    source: str
    codes: list[str]


@dataclass(frozen=True, slots=True)
class KOSDAQ150RefreshResult:
    as_of: date
    source: str
    path: Path
    previous_count: int
    current_count: int
    added: list[str]
    removed: list[str]
    updated: bool


def get_kosdaq150(as_of: date | str, *, allow_fallback: bool = True) -> list[str]:
    """Return KOSDAQ150 constituent stock codes as of a given date."""

    return resolve_kosdaq150(as_of, allow_fallback=allow_fallback).codes


async def get_kosdaq150_async(as_of: date | str) -> list[str]:
    import asyncio

    return await asyncio.to_thread(get_kosdaq150, as_of)


def resolve_kosdaq150(
    as_of: date | str,
    *,
    allow_fallback: bool = True,
    prefer_cache: bool = True,
    include_manual_file: bool = True,
) -> ResolvedKOSDAQ150:
    """Resolve KOSDAQ150 codes and retain the source used."""

    resolved_date = _to_date(as_of)
    date_text = _to_yyyymmdd(as_of)

    codes = _from_pykrx_index(date_text)
    if codes:
        _write_cache(date_text, codes, source="krx_index")
        return ResolvedKOSDAQ150(
            as_of=resolved_date,
            source="pykrx:krx_index",
            codes=codes,
        )

    if not allow_fallback:
        return ResolvedKOSDAQ150(as_of=resolved_date, source="none", codes=[])

    if prefer_cache and (cached := _read_exact_cache(date_text)):
        print(
            "[phase2:warn] using cached KOSDAQ150 constituents for "
            f"{date_text}: {len(cached)} codes"
        )
        return ResolvedKOSDAQ150(
            as_of=resolved_date,
            source="cache:exact_date",
            codes=cached,
        )

    codes = _from_fdr_index_snapshot()
    if codes:
        print(
            "[phase2:warn] using FinanceDataReader KRX index snapshot "
            f"fallback for KOSDAQ150: {len(codes)} codes"
        )
        _write_cache(date_text, codes, source="fdr_krx_index_snapshot")
        return ResolvedKOSDAQ150(
            as_of=resolved_date,
            source="fdr:krx_index_snapshot",
            codes=codes,
        )

    codes = _approximate_top_kosdaq_by_size(date_text, limit=150)
    if codes:
        print(
            "[phase2:warn] using approximate KOSDAQ150 fallback: "
            f"top {len(codes)} KOSDAQ stocks by market cap/current listing"
        )
        _write_cache(date_text, codes, source="approx_top_kosdaq")
        return ResolvedKOSDAQ150(
            as_of=resolved_date,
            source="approx:top_kosdaq_by_size",
            codes=codes,
        )

    cached = _read_latest_cache()
    if cached:
        print(
            "[phase2:warn] using latest cached KOSDAQ150 constituents: "
            f"{len(cached)} codes"
        )
        return ResolvedKOSDAQ150(
            as_of=resolved_date,
            source="cache:latest",
            codes=cached,
        )

    if include_manual_file:
        manual_codes = _from_manual_codes_file(minimum=MIN_DB_FALLBACK_CODES)
        if manual_codes:
            print(
                "[phase2:warn] using manual KOSDAQ150 codes file fallback: "
                f"{len(manual_codes)} codes"
            )
            return ResolvedKOSDAQ150(
                as_of=resolved_date,
                source="manual:kosdaq150_codes_file",
                codes=manual_codes,
            )

    db_codes = _from_research_db(resolved_date, minimum=MIN_DB_FALLBACK_CODES)
    if db_codes:
        print(
            "[phase2:warn] using research.db KOSDAQ stock fallback: "
            f"{len(db_codes)} codes"
        )
        return ResolvedKOSDAQ150(
            as_of=resolved_date,
            source="research_db:kosdaq_stocks",
            codes=db_codes,
        )

    return ResolvedKOSDAQ150(as_of=resolved_date, source="none", codes=[])


def refresh_kosdaq150_codes_file(
    *,
    as_of: date | str | None = None,
    path: Path = KOSDAQ150_CODES_FILE,
    min_codes: int = MIN_REFRESH_CODES,
) -> KOSDAQ150RefreshResult:
    """Fetch the latest KOSDAQ150 list and update the manual CSV when changed."""

    resolved = resolve_kosdaq150(
        as_of or date.today(),
        allow_fallback=True,
        prefer_cache=False,
        include_manual_file=False,
    )
    if len(resolved.codes) < min_codes:
        raise RuntimeError(
            "KOSDAQ150 refresh resolved too few codes: "
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

    return KOSDAQ150RefreshResult(
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
    from pykrx import stock

    try:
        codes = stock.get_index_portfolio_deposit_file(
            KOSDAQ150_INDEX_CODE,
            date_text,
            alternative=True,
        )
    except Exception as exc:
        print(f"[phase2:warn] KOSDAQ150 constituent lookup failed: {exc}")
        return []
    return sorted({str(code).zfill(6) for code in codes})


def _write_codes_file(
    path: Path,
    codes: list[str],
    *,
    as_of: date,
    source: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# KOSDAQ150 manual universe fallback",
        "# Auto-updated by /api/settings/universe/kosdaq150/refresh.",
        f"# as_of={as_of.isoformat()}",
        f"# source={source}",
        "",
        *codes,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _from_fdr_index_snapshot() -> list[str]:
    try:
        import FinanceDataReader as fdr

        frame = fdr.SnapDataReader(f"KRX/INDEX/STOCK/{KOSDAQ150_INDEX_CODE}")
    except Exception as exc:
        print(f"[phase2:warn] FinanceDataReader KOSDAQ150 snapshot failed: {exc}")
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


def _approximate_top_kosdaq_by_size(date_text: str, *, limit: int) -> list[str]:
    codes = _top_kosdaq_by_pykrx_market_cap(date_text, limit=limit)
    if codes:
        return codes

    codes = _top_kosdaq_by_fdr_listing(limit=limit)
    if codes:
        return codes

    codes = _kosdaq_ticker_list_by_pykrx(date_text, limit=limit)
    if codes:
        print(
            "[phase2:warn] market-cap ranking unavailable; "
            "falling back to first KOSDAQ ticker-list codes"
        )
        return codes

    return []


def _top_kosdaq_by_pykrx_market_cap(date_text: str, *, limit: int) -> list[str]:
    from pykrx import stock

    for candidate in _date_candidates(date_text):
        try:
            frame = stock.get_market_cap_by_ticker(candidate, market="KOSDAQ")
        except Exception as exc:
            print(f"[phase2:warn] pykrx KOSDAQ market-cap fallback failed: {exc}")
            return []
        if frame is None or frame.empty or "시가총액" not in frame.columns:
            continue
        frame = frame.sort_values("시가총액", ascending=False)
        return _normalize_codes(frame.index)[:limit]
    return []


def _top_kosdaq_by_fdr_listing(*, limit: int) -> list[str]:
    try:
        import FinanceDataReader as fdr
    except Exception as exc:
        print(f"[phase2:warn] FinanceDataReader import failed: {exc}")
        return []

    try:
        frame = fdr.StockListing("KOSDAQ")
    except Exception as exc:
        print(f"[phase2:warn] FinanceDataReader KOSDAQ listing failed: {exc}")
        try:
            frame = fdr.StockListing("KRX")
        except Exception as fallback_exc:
            print(f"[phase2:warn] FinanceDataReader KRX listing failed: {fallback_exc}")
            return []

    if frame is None or frame.empty:
        return []

    if "Market" in frame.columns:
        frame = frame[frame["Market"].astype(str).str.upper().eq("KOSDAQ")]

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


def _kosdaq_ticker_list_by_pykrx(date_text: str, *, limit: int) -> list[str]:
    from pykrx import stock

    for candidate in _date_candidates(date_text):
        try:
            codes = stock.get_market_ticker_list(candidate, "KOSDAQ")
        except Exception as exc:
            print(f"[phase2:warn] pykrx KOSDAQ ticker fallback failed: {exc}")
            return []
        normalized = _normalize_codes(codes)
        if normalized:
            return normalized[:limit]
    return []


def _from_research_db(as_of: date, *, minimum: int) -> list[str]:
    sql = """
        SELECT code
        FROM stocks
        WHERE market = 'KOSDAQ'
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
                "[phase2:warn] research.db KOSDAQ fallback has only "
                f"{len(codes)} codes; refusing to treat it as a full universe"
            )
        return []
    return codes


def _from_manual_codes_file(*, minimum: int) -> list[str]:
    codes = _read_codes_file(KOSDAQ150_CODES_FILE)
    if len(codes) < minimum:
        return []
    return codes


def _write_cache(date_text: str, codes: list[str], *, source: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"as_of": date_text, "source": source, "codes": codes}
        (CACHE_DIR / f"kosdaq150_{date_text}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


def _read_exact_cache(date_text: str) -> list[str]:
    return _read_cache_file(CACHE_DIR / f"kosdaq150_{date_text}.json")


def _read_latest_cache() -> list[str]:
    try:
        paths = sorted(CACHE_DIR.glob("kosdaq150_*.json"), reverse=True)
    except OSError:
        return []
    for path in paths:
        codes = _read_cache_file(path)
        if codes:
            return codes
    return []
