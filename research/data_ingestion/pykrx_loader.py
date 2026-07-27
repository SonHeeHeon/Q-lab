"""pykrx-based OHLCV, index, and listed-stock loaders."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.exc import OperationalError
from sqlalchemy.dialects.sqlite import insert

os.environ.setdefault("MPLCONFIGDIR", str(Path("/private/tmp/qlab-mplconfig")))

from shared.db.models import (
    InvestorFlowDaily,
    MarketCapDaily,
    MarketIndex,
    PriceDaily,
    Stock,
)
from shared.db.session import research_session

logger = logging.getLogger(__name__)

MARKET_INDEX_TICKERS = {
    "KOSPI": "1001",
    "KOSDAQ": "2001",
}

FDR_INDEX_TICKERS = {
    "KOSPI": "KS11",
    "KOSDAQ": "KQ11",
}

SQLITE_LOCK_RETRY_ATTEMPTS = 8
SQLITE_LOCK_RETRY_BASE_SECONDS = 0.25
_DB_WRITE_LOCK = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class LoadResult:
    name: str
    requested: int
    inserted_or_ignored: int


async def update_universe(
    market: str,
    *,
    as_of: date,
    listed_at_default: date,
) -> LoadResult:
    """Upsert currently listed stock metadata for one KRX market."""

    market = market.upper()
    stock = _pykrx_stock()
    try:
        codes = await asyncio.to_thread(
            stock.get_market_ticker_list,
            _to_yyyymmdd(as_of),
            market,
        )
    except Exception as exc:
        print(f"[phase2:warn] pykrx ticker list failed for {market}: {exc}")
        codes = []
    rows = []
    for code in sorted({str(code).zfill(6) for code in codes}):
        name = await asyncio.to_thread(stock.get_market_ticker_name, code)
        rows.append(
            {
                "code": code,
                "name": name or code,
                "market": market,
                "sector": None,
                "industry": None,
                "listed_at": listed_at_default,
                "delisted_at": None,
                "is_delisted": False,
            }
        )

    await _upsert_stock_rows(rows)
    return LoadResult(name=f"stocks:{market}", requested=len(rows), inserted_or_ignored=len(rows))


async def ensure_stock_rows(
    codes: Iterable[str],
    *,
    market: str = "KOSPI",
    listed_at_default: date,
) -> LoadResult:
    stock = _pykrx_stock()
    rows = []
    for code in sorted({str(code).zfill(6) for code in codes}):
        try:
            name = await asyncio.to_thread(stock.get_market_ticker_name, code)
        except Exception:
            name = code
        rows.append(
            {
                "code": code,
                "name": name or code,
                "market": market,
                "sector": None,
                "industry": None,
                "listed_at": listed_at_default,
                "delisted_at": None,
                "is_delisted": False,
            }
        )
    await _upsert_stock_rows(rows)
    return LoadResult(name=f"stocks:{market}:selected", requested=len(rows), inserted_or_ignored=len(rows))


async def update_prices(
    codes: Iterable[str],
    *,
    start: date,
    end: date,
    concurrency: int = 4,
    sleep_seconds: float = 0.15,
) -> LoadResult:
    """Download adjusted daily OHLCV and insert into prices_daily."""

    semaphore = asyncio.Semaphore(concurrency)
    total_rows = 0

    async def load_one(code: str) -> int:
        async with semaphore:
            # pykrx가 죽어 있으면(KRX 차단 등) 조용히 FDR로 간다 — 원인은
            # _pykrx_stock()이 1회만 로깅하므로 종목마다 반복 출력하지 않는다.
            stock = _pykrx_stock_or_none()
            df = None
            if stock is not None:
                try:
                    df = await asyncio.to_thread(
                        stock.get_market_ohlcv_by_date,
                        _to_yyyymmdd(start),
                        _to_yyyymmdd(end),
                        code,
                        "d",
                        True,
                    )
                except Exception as exc:
                    _warn_once(
                        "price", f"pykrx 가격 조회 실패 — FDR로 대체합니다: {exc}"
                    )
                    df = None
            if df is None:
                df = await asyncio.to_thread(_fdr_price_frame, code, start, end)
            await asyncio.sleep(sleep_seconds)
        rows = _price_rows_from_frame(code, df)
        await _insert_ignore(PriceDaily, rows)
        return len(rows)

    for rows_count in await asyncio.gather(
        *(load_one(str(code).zfill(6)) for code in codes)
    ):
        total_rows += rows_count

    return LoadResult(name="prices_daily", requested=total_rows, inserted_or_ignored=total_rows)


async def update_market_index(
    index_code: str,
    *,
    start: date,
    end: date,
) -> LoadResult:
    """Download KOSPI/KOSDAQ daily close into market_index."""

    stock = _pykrx_stock()
    ticker = MARKET_INDEX_TICKERS[index_code.upper()]
    try:
        df = await asyncio.to_thread(
            stock.get_index_ohlcv_by_date,
            _to_yyyymmdd(start),
            _to_yyyymmdd(end),
            ticker,
            "d",
            False,
        )
    except Exception:
        logger.warning(
            "pykrx index failed for %s (range %s..%s); falling back to FDR",
            index_code.upper(),
            start,
            end,
            exc_info=True,
        )
        df = await asyncio.to_thread(_fdr_index_frame, index_code.upper(), start, end)
    rows = []
    for row_date, row in df.iterrows():
        close = _pick(row, "종가", "Close", "close")
        if close is None:
            continue
        rows.append(
            {
                "index_code": index_code.upper(),
                "date": _to_date(row_date),
                "close": _to_decimal(close),
            }
        )
    if not rows:
        logger.warning(
            "no index rows returned for %s in range %s..%s "
            "(both pykrx and FDR yielded nothing)",
            index_code.upper(),
            start,
            end,
        )
    await _insert_ignore(MarketIndex, rows)
    return LoadResult(name=f"market_index:{index_code.upper()}", requested=len(rows), inserted_or_ignored=len(rows))


async def update_market_indices(*, start: date, end: date) -> list[LoadResult]:
    return [
        await update_market_index("KOSPI", start=start, end=end),
        await update_market_index("KOSDAQ", start=start, end=end),
    ]


async def update_market_caps(
    codes: Iterable[str],
    *,
    start: date,
    end: date,
    concurrency: int = 4,
    sleep_seconds: float = 0.15,
) -> LoadResult:
    """Download true daily market caps (시가총액/상장주식수) into market_caps.

    Feeds the engine's MARKET_CAP factor/filter, which no longer substitutes a
    turnover proxy. pykrx-only (FDR carries no historical caps); a code that
    fails is skipped with a warning rather than silently proxied.
    """

    semaphore = asyncio.Semaphore(concurrency)
    total_rows = 0

    async def load_one(code: str) -> int:
        # pykrx 전용(FDR에는 과거 시총이 없다) — 죽어 있으면 조용히 건너뛴다.
        stock = _pykrx_stock_or_none()
        if stock is None:
            return 0
        async with semaphore:
            # 세마포어 안에서 다시 확인 — gather가 모든 코루틴을 한꺼번에 띄우므로
            # 진입 시점 검사만으로는 앞선 종목의 실패를 반영할 수 없다.
            if _krx_portal_broken:
                return 0
            try:
                df = await asyncio.to_thread(
                    stock.get_market_cap_by_date,
                    _to_yyyymmdd(start),
                    _to_yyyymmdd(end),
                    code,
                )
            except Exception as exc:
                _mark_krx_portal_broken()
                _warn_once(
                    "market_cap",
                    f"pykrx 시총 조회 실패 — KRX 포털 무응답, 남은 종목 생략: {exc}",
                )
                return 0
            await asyncio.sleep(sleep_seconds)
        rows = _market_cap_rows_from_frame(code, df)
        _note_krx_ok() if rows else _note_krx_empty("market_cap")
        await _insert_ignore(MarketCapDaily, rows)
        return len(rows)

    for rows_count in await asyncio.gather(
        *(load_one(str(code).zfill(6)) for code in codes)
    ):
        total_rows += rows_count

    return LoadResult(
        name="market_caps", requested=total_rows, inserted_or_ignored=total_rows
    )


async def update_investor_flows(
    codes: Iterable[str],
    *,
    start: date,
    end: date,
    concurrency: int = 4,
    sleep_seconds: float = 0.15,
) -> LoadResult:
    """Download daily net-purchase value by investor type (투자자별 순매수).

    Source: pykrx get_market_trading_value_by_date per ticker — columns are
    net purchase trading values (KRW, buy − sell). Feeds the Flow factor group
    (FOREIGN_NET_20D / INST_NET_20D). Requires KRX data-portal login
    (KRX_ID / KRX_PW in the environment) like the other pykrx endpoints.
    """

    semaphore = asyncio.Semaphore(concurrency)
    total_rows = 0

    async def load_one(code: str) -> int:
        # pykrx(KRX 포털) 전용 — 죽어 있으면 조용히 건너뛴다(Flow 팩터만 비게 됨).
        stock = _pykrx_stock_or_none()
        if stock is None:
            return 0
        async with semaphore:
            # 세마포어 안에서 다시 확인(위 update_market_caps와 같은 이유).
            if _krx_portal_broken:
                return 0
            try:
                df = await asyncio.to_thread(
                    stock.get_market_trading_value_by_date,
                    _to_yyyymmdd(start),
                    _to_yyyymmdd(end),
                    code,
                )
            except Exception as exc:
                _mark_krx_portal_broken()
                _warn_once(
                    "investor_flows",
                    f"pykrx 수급 조회 실패 — KRX 포털 무응답, 남은 종목 생략: {exc}",
                )
                return 0
            await asyncio.sleep(sleep_seconds)
        rows = _investor_flow_rows_from_frame(code, df)
        _note_krx_ok() if rows else _note_krx_empty("investor_flows")
        await _insert_ignore(InvestorFlowDaily, rows)
        return len(rows)

    for rows_count in await asyncio.gather(
        *(load_one(str(code).zfill(6)) for code in codes)
    ):
        total_rows += rows_count

    return LoadResult(
        name="investor_flows_daily",
        requested=total_rows,
        inserted_or_ignored=total_rows,
    )


_FLOW_COLUMN_ALIASES = {
    "foreign_net": ("외국인합계", "외국인"),
    "inst_net": ("기관합계", "기관"),
    "indiv_net": ("개인",),
}


def _investor_flow_rows_from_frame(code: str, df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        values: dict[str, Decimal | None] = {}
        for field, aliases in _FLOW_COLUMN_ALIASES.items():
            raw = next(
                (row[alias] for alias in aliases if alias in row.index), None
            )
            values[field] = (
                Decimal(str(int(raw))) if raw is not None and pd.notna(raw) else None
            )
        if all(value is None for value in values.values()):
            continue
        rows.append({"stock_code": code, "date": _to_date(idx), **values})
    return rows


def _market_cap_rows_from_frame(code: str, df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        cap = row.get("시가총액")
        if cap is None or pd.isna(cap):
            continue
        shares = row.get("상장주식수")
        rows.append(
            {
                "stock_code": code,
                "date": _to_date(idx),
                "market_cap": Decimal(str(int(cap))),
                "shares_outstanding": int(shares) if pd.notna(shares) else None,
            }
        )
    return rows


async def get_trading_days(start: date, end: date) -> list[date]:
    stock = _pykrx_stock()
    try:
        df = await asyncio.to_thread(
            stock.get_index_ohlcv_by_date,
            _to_yyyymmdd(start),
            _to_yyyymmdd(end),
            MARKET_INDEX_TICKERS["KOSPI"],
            "d",
            False,
        )
    except Exception:
        df = await asyncio.to_thread(_fdr_index_frame, "KOSPI", start, end)
    return [_to_date(idx) for idx in df.index]


async def _upsert_stock_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with _DB_WRITE_LOCK:
        await _with_sqlite_lock_retries(_upsert_stock_rows_once, rows)


async def _upsert_stock_rows_once(rows: list[dict[str, Any]]) -> None:
    async with research_session() as session:
        for chunk in _chunks(rows, _safe_insert_chunk_size(rows)):
            stmt = insert(Stock).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Stock.code],
                set_={
                    "name": stmt.excluded.name,
                    "market": stmt.excluded.market,
                    "sector": stmt.excluded.sector,
                    "industry": stmt.excluded.industry,
                },
            )
            await session.execute(stmt)
        await session.commit()


async def _insert_ignore(model: Any, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with _DB_WRITE_LOCK:
        await _with_sqlite_lock_retries(_insert_ignore_once, model, rows)


async def _insert_ignore_once(model: Any, rows: list[dict[str, Any]]) -> None:
    async with research_session() as session:
        for chunk in _chunks(rows, _safe_insert_chunk_size(rows)):
            stmt = insert(model).values(chunk).on_conflict_do_nothing()
            await session.execute(stmt)
        await session.commit()


async def _with_sqlite_lock_retries(operation: Any, *args: Any) -> None:
    for attempt in range(SQLITE_LOCK_RETRY_ATTEMPTS):
        try:
            await operation(*args)
            return
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            if attempt == SQLITE_LOCK_RETRY_ATTEMPTS - 1:
                raise
            delay = SQLITE_LOCK_RETRY_BASE_SECONDS * (2**attempt)
            print(
                "[phase2:warn] SQLite database is locked during research write; "
                f"retrying in {delay:.2f}s"
            )
            await asyncio.sleep(delay)


def _safe_insert_chunk_size(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 1
    column_count = max(1, len(rows[0]))
    return max(1, 900 // column_count)


def _chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _price_rows_from_frame(code: str, df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    if df is None or df.empty:
        return rows
    for row_date, row in df.iterrows():
        open_ = _pick(row, "시가", "Open", "open")
        high = _pick(row, "고가", "High", "high")
        low = _pick(row, "저가", "Low", "low")
        close = _pick(row, "종가", "Close", "close")
        volume = _pick(row, "거래량", "Volume", "volume")
        if any(value is None for value in (open_, high, low, close, volume)):
            continue
        rows.append(
            {
                "stock_code": code,
                "date": _to_date(row_date),
                "open": _to_decimal(open_),
                "high": _to_decimal(high),
                "low": _to_decimal(low),
                "close": _to_decimal(close),
                "volume": int(volume),
                "adj_close": _to_decimal(close),
            }
        )
    return rows


def _pick(row: pd.Series, *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _to_yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _to_date(value: Any) -> date:
    return pd.Timestamp(value).date()


def _to_decimal(value: Any) -> Decimal:
    return Decimal(str(value).replace(",", ""))


_pykrx_import_error: Exception | None = None


def _pykrx_stock():
    """pykrx의 ``stock`` 모듈.

    KRX 자격증명(KRX_ID/KRX_PW)이 환경에 있으면 pykrx는 **import 시점에** KRX
    데이터포털 로그인을 시도한다. 포털이 차단(Akamai "Access Denied")되면 로그인
    응답이 HTML이라 JSON 파싱에서 죽고, 파이썬은 실패한 import를 캐시하지 않으므로
    호출 지점마다(=종목마다) 로그인 HTTP 요청이 새로 나간다. 수백 회 폭주가 백엔드
    스레드를 포화시켜 모든 API가 무응답이 됐다. 첫 실패를 캐시해 이후엔 즉시 포기한다.
    """
    global _pykrx_import_error
    if _pykrx_import_error is not None:
        raise _pykrx_import_error
    try:
        from pykrx import stock
    except Exception as exc:  # noqa: BLE001 - import-time KRX login can fail any way
        _pykrx_import_error = exc
        print(f"[pykrx:warn] import 실패 — 이후 pykrx 경로는 건너뜁니다: {exc}")
        raise
    return stock


def _pykrx_stock_or_none():
    """pykrx ``stock`` 모듈, 또는 import가 이미 실패했으면 ``None``.

    호출자는 None이면 **경고 없이** 폴백하거나 건너뛴다. 원인은 최초 1회만
    남기면 충분한데, 종목마다 예외를 잡아 출력하면 같은 줄이 수백 개 쌓여
    로그를 뒤덮기 때문이다.
    """
    try:
        return _pykrx_stock()
    except Exception:  # noqa: BLE001 - 원인은 _pykrx_stock()이 1회 로깅함
        return None


# KRX 데이터포털(시총·수급)이 응답하지 않는 것으로 확인되면 True. 남은 종목은
# 호출조차 하지 않는다 — 차단 상태에선 수백 번 왕복해도 전부 실패하고, pykrx가
# 내부적으로 찍는 에러 줄("Error occurred in __fetch: ...")이 로그를 뒤덮는다.
# 프로세스를 다시 띄우면 초기화되므로 차단이 풀리면 자연히 재시도된다.
_krx_portal_broken = False


def _mark_krx_portal_broken() -> None:
    global _krx_portal_broken
    _krx_portal_broken = True


# pykrx는 포털이 막혀도 예외를 던지지 않는다 — 내부에서 에러를 print한 뒤 빈
# DataFrame을 돌려준다. 따라서 예외만으로는 차단을 감지할 수 없어 "연속 빈 응답"
# 을 함께 본다. 정상 종목이 어쩌다 비는 경우(신규 상장 등)로 오작동하지 않도록
# 성공이 하나라도 나오면 연속 카운터를 리셋한다.
_krx_empty_streak = 0
_KRX_EMPTY_LIMIT = 5


def _note_krx_empty(kind: str) -> None:
    global _krx_empty_streak
    _krx_empty_streak += 1
    if _krx_empty_streak >= _KRX_EMPTY_LIMIT:
        _mark_krx_portal_broken()
        _warn_once(
            kind,
            f"KRX 포털이 연속 {_KRX_EMPTY_LIMIT}회 빈 응답 — 남은 종목은 생략합니다"
            " (차단 해제 후 백엔드를 재시작하면 다시 시도).",
        )


def _note_krx_ok() -> None:
    global _krx_empty_streak
    _krx_empty_streak = 0


_warned_keys: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    """같은 원인의 경고를 1회만 출력한다(종목 수만큼 반복되는 로그 폭주 방지)."""
    if key in _warned_keys:
        return
    _warned_keys.add(key)
    print(f"[phase2:warn] {message}")


def _fdr_price_frame(code: str, start: date, end: date) -> pd.DataFrame:
    try:
        import FinanceDataReader as fdr

        return fdr.DataReader(code, start, end)
    except Exception as exc:
        _warn_once(
            "fdr_price", f"FinanceDataReader 가격 조회 실패(이후 종목 생략): {exc}"
        )
        return pd.DataFrame()


def _fdr_index_frame(index_code: str, start: date, end: date) -> pd.DataFrame:
    try:
        import FinanceDataReader as fdr

        return fdr.DataReader(FDR_INDEX_TICKERS[index_code], start, end)
    except Exception:
        logger.warning(
            "FinanceDataReader index failed for %s", index_code, exc_info=True
        )
        return pd.DataFrame()
