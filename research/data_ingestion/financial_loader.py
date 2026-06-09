"""DART OpenAPI quarterly financial statement loader."""

from __future__ import annotations

import asyncio
import io
import os
import ssl
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree

import aiohttp
import certifi
from sqlalchemy.dialects.sqlite import insert

from shared.db.models import Financial
from shared.db.session import research_session

DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
DART_FINANCIAL_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

REPORTS = {
    "11013": date(2000, 3, 31),
    "11012": date(2000, 6, 30),
    "11014": date(2000, 9, 30),
    "11011": date(2000, 12, 31),
}

# SQLite builds differ in their host parameter limit. Financial rows currently
# insert 10 columns each, so 90 rows stays under the conservative 999-variable
# limit while still keeping writes efficient enough for overnight loads.
SQLITE_SAFE_INSERT_CHUNK_SIZE = 90

ACCOUNT_ALIASES = {
    "revenue": {
        "ifrs-full_Revenue",
        "ifrs-full_RevenueFromContractsWithCustomersExcludingAssessedTax",
        "매출액",
        "수익(매출액)",
        "영업수익",
    },
    "operating_income": {"dart_OperatingIncomeLoss", "영업이익"},
    "net_income": {
        "ifrs-full_ProfitLoss",
        "ifrs-full_ProfitLossAttributableToOwnersOfParent",
        "당기순이익",
        "분기순이익",
        "반기순이익",
    },
    "total_assets": {"ifrs-full_Assets", "자산총계"},
    "total_equity": {
        "ifrs-full_Equity",
        "ifrs-full_EquityAttributableToOwnersOfParent",
        "자본총계",
    },
    "eps": {
        "ifrs-full_BasicEarningsLossPerShare",
        "ifrs-full_DilutedEarningsLossPerShare",
        "기본주당이익",
        "기본주당순이익",
    },
}


@dataclass(frozen=True, slots=True)
class FinancialLoadResult:
    requested_reports: int
    parsed_rows: int


async def update_financials(
    codes: list[str],
    *,
    since_year: int,
    until_year: int,
    concurrency: int = 2,
    sleep_seconds: float = 0.2,
) -> FinancialLoadResult:
    """Download quarterly financials from DART and insert idempotently."""

    api_key = os.getenv("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DART_API_KEY is required to download financials.")

    corp_map = await fetch_corp_code_map(api_key)
    semaphore = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit_per_host=concurrency, ssl=_ssl_context())
    requested_reports = 0
    parsed_rows: list[dict[str, Any]] = []

    async with aiohttp.ClientSession(connector=connector) as http:
        tasks = []
        for code in sorted({str(code).zfill(6) for code in codes}):
            corp_code = corp_map.get(code)
            if not corp_code:
                continue
            for year in range(since_year, until_year + 1):
                for report_code in REPORTS:
                    requested_reports += 1
                    tasks.append(
                        _fetch_one_report(
                            http,
                            semaphore,
                            api_key=api_key,
                            stock_code=code,
                            corp_code=corp_code,
                            year=year,
                            report_code=report_code,
                            sleep_seconds=sleep_seconds,
                        )
                    )

        for result in await asyncio.gather(*tasks):
            if result is not None:
                parsed_rows.append(result)

    await _insert_ignore_financials(parsed_rows)
    return FinancialLoadResult(
        requested_reports=requested_reports,
        parsed_rows=len(parsed_rows),
    )


async def fetch_corp_code_map(api_key: str) -> dict[str, str]:
    connector = aiohttp.TCPConnector(ssl=_ssl_context())
    async with aiohttp.ClientSession(connector=connector) as http:
        async with http.get(DART_CORP_CODE_URL, params={"crtfc_key": api_key}) as resp:
            content = await resp.read()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml_bytes = archive.read("CORPCODE.xml")

    root = ElementTree.fromstring(xml_bytes)
    mapping: dict[str, str] = {}
    for item in root.findall("list"):
        corp_code = _xml_text(item, "corp_code")
        stock_code = _xml_text(item, "stock_code")
        if corp_code and stock_code:
            mapping[stock_code.zfill(6)] = corp_code
    return mapping


async def _fetch_one_report(
    http: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    *,
    api_key: str,
    stock_code: str,
    corp_code: str,
    year: int,
    report_code: str,
    sleep_seconds: float,
) -> dict[str, Any] | None:
    async with semaphore:
        params = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": report_code,
            "fs_div": "CFS",
        }
        async with http.get(DART_FINANCIAL_URL, params=params) as resp:
            payload = await resp.json(content_type=None)
        await asyncio.sleep(sleep_seconds)

    if payload.get("status") == "013":
        return None
    if payload.get("status") not in (None, "000"):
        return None
    return parse_dart_response(stock_code, year, report_code, payload)


def parse_dart_response(
    stock_code: str,
    year: int,
    report_code: str,
    raw: dict[str, Any],
) -> dict[str, Any] | None:
    items = raw.get("list")
    if not isinstance(items, list) or not items:
        return None

    metrics: dict[str, Decimal | None] = {
        "revenue": None,
        "operating_income": None,
        "net_income": None,
        "total_assets": None,
        "total_equity": None,
        "eps": None,
        "bps": None,
    }
    disclosed_at: date | None = None

    for item in items:
        if not isinstance(item, dict):
            continue
        disclosed_at = disclosed_at or _disclosed_at(item, year, report_code)
        account_id = str(item.get("account_id") or "")
        account_name = str(item.get("account_nm") or "")
        amount = _amount(item.get("thstrm_amount"))
        if amount is None:
            continue
        for metric, aliases in ACCOUNT_ALIASES.items():
            if metrics[metric] is None and (
                account_id in aliases or account_name in aliases
            ):
                metrics[metric] = amount

    if disclosed_at is None:
        disclosed_at = _fallback_disclosed_at(year, report_code)

    fiscal_period = _fiscal_period(year, report_code)
    return {
        "stock_code": stock_code,
        "fiscal_period": fiscal_period,
        "disclosed_at": disclosed_at,
        **metrics,
    }


async def _insert_ignore_financials(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with research_session() as session:
        for chunk in _chunks(rows, SQLITE_SAFE_INSERT_CHUNK_SIZE):
            stmt = insert(Financial).values(chunk).on_conflict_do_nothing()
            await session.execute(stmt)
        await session.commit()


def _chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _disclosed_at(item: dict[str, Any], year: int, report_code: str) -> date:
    rcept_no = str(item.get("rcept_no") or "")
    if len(rcept_no) >= 8 and rcept_no[:8].isdigit():
        return date(
            int(rcept_no[:4]),
            int(rcept_no[4:6]),
            int(rcept_no[6:8]),
        )
    return _fallback_disclosed_at(year, report_code)


def _fallback_disclosed_at(year: int, report_code: str) -> date:
    base = _fiscal_period(year, report_code)
    if report_code == "11011":
        return base + timedelta(days=90)
    return base + timedelta(days=45)


def _fiscal_period(year: int, report_code: str) -> date:
    template = REPORTS[report_code]
    return date(year, template.month, template.day)


def _amount(value: Any) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _xml_text(item: ElementTree.Element, tag: str) -> str:
    child = item.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())
