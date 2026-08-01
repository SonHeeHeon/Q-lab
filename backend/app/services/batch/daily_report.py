"""Daily LLM commentary and Telegram report job."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date as Date
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select

from backend.app.core.config import PROJECT_ROOT, settings
from backend.app.services.batch.daily_analysis import latest_research_price_date
from backend.app.services.llm.cache import complete_cached
from backend.app.services.llm.client import LLMError
from backend.app.services.notify.telegram import (
    TelegramSendError,
    TelegramSendResult,
    send_markdown,
)
from shared.db.models import BatchAnalysisResult, Setting
from shared.db.session import research_db_path, service_session

import logging

logger = logging.getLogger(__name__)

PROMPTS_DIR = PROJECT_ROOT / "backend" / "app" / "services" / "llm" / "prompts"

# LLM 코멘터리 실행 정책 — "on_view"(기본): 사용자가 인사이트를 조회할 때 1회
# 생성(같은 날 재조회는 저장분 반환, 비용 절감). "scheduled": 크론이 매일 생성.
ON_VIEW_NOTICE = (
    "LLM 코멘터리는 '조회 시 생성' 모드입니다 — 앱 인사이트 탭을 열면 "
    "그날 1회 생성됩니다."
)


async def llm_commentary_mode() -> str:
    """Setting llm_commentary_mode — 'scheduled' 외의 값/부재는 'on_view'."""
    async with service_session() as session:
        row = await session.get(Setting, "llm_commentary_mode")
    if row is not None and str(row.value).strip().lower() == "scheduled":
        return "scheduled"
    return "on_view"


async def generate_and_store_commentary(
    analysis_date: Date, strategy_name: str, *, limit: int = 10
) -> bool:
    """코멘터리 생성→(analysis_date, strategy) 키로 저장 — 크론·조회 트리거 공용.

    성공 True, 실패(예산 초과·LLM 오류 등)는 로그 후 False — 실패 시 저장하지
    않아 다음 조회가 재시도할 수 있다.
    """
    rows = await _load_analysis_rows(analysis_date, strategy_name, limit)
    stocks = await asyncio.to_thread(_hydrate_stocks, rows)
    if not stocks:
        logger.info(
            "commentary skipped — no analysis rows (%s, %s)",
            analysis_date, strategy_name,
        )
        return False
    prompt = render_undervalued_prompt(
        analysis_date=analysis_date, strategy_name=strategy_name, stocks=stocks
    )
    try:
        commentary = await complete_cached(prompt, max_tokens=900)
    except Exception:  # noqa: BLE001 — 실패는 재시도 가능해야 함
        logger.exception("lazy commentary generation failed")
        return False
    await _update_commentary(analysis_date, strategy_name, commentary)
    return True


@dataclass(frozen=True, slots=True)
class DailyReportStock:
    code: str
    name: str
    sector: str | None
    score: float
    rank: int


@dataclass(frozen=True, slots=True)
class DailyReportResult:
    analysis_date: Date
    strategy_name: str
    stocks: list[DailyReportStock]
    commentary: str
    llm_fallback_used: bool
    telegram: TelegramSendResult


async def run_daily_report(
    *,
    analysis_date: Date | None = None,
    strategy_name: str | None = None,
    limit: int = 10,
    send_telegram: bool = True,
    strict_llm: bool = False,
) -> DailyReportResult:
    """Create LLM commentary for the latest analysis rows and optionally send Telegram."""

    as_of = analysis_date or latest_research_price_date()
    selected_strategy = strategy_name or settings.DEFAULT_STRATEGY_NAME
    analysis_rows = await _load_analysis_rows(as_of, selected_strategy, limit)
    stocks = await asyncio.to_thread(_hydrate_stocks, analysis_rows)

    # on_view 모드: 크론 경로에선 LLM을 돌리지 않는다 — 조회 트리거(lazy)가
    # 채울 자리를 비워 두고, 텔레그램 리포트에는 안내 문구만 싣는다.
    if not strict_llm and await llm_commentary_mode() == "on_view":
        telegram_result = await _send_daily_report_message(
            as_of, selected_strategy, stocks, ON_VIEW_NOTICE,
            send_telegram=send_telegram,
        )
        return DailyReportResult(
            analysis_date=as_of,
            strategy_name=selected_strategy,
            stocks=stocks,
            commentary=ON_VIEW_NOTICE,
            llm_fallback_used=False,
            telegram=telegram_result,
        )

    prompt = render_undervalued_prompt(
        analysis_date=as_of,
        strategy_name=selected_strategy,
        stocks=stocks,
    )
    llm_fallback_used = False
    try:
        commentary = await complete_cached(prompt, max_tokens=900)
    except Exception as exc:
        if strict_llm:
            raise
        llm_fallback_used = True
        commentary = _fallback_commentary(exc, stocks)

    await _update_commentary(as_of, selected_strategy, commentary)
    telegram_result = await _send_daily_report_message(
        as_of,
        selected_strategy,
        stocks,
        commentary,
        send_telegram=send_telegram,
    )
    return DailyReportResult(
        analysis_date=as_of,
        strategy_name=selected_strategy,
        stocks=stocks,
        commentary=commentary,
        llm_fallback_used=llm_fallback_used,
        telegram=telegram_result,
    )


def render_undervalued_prompt(
    *,
    analysis_date: Date,
    strategy_name: str,
    stocks: list[DailyReportStock],
) -> str:
    env = Environment(
        loader=FileSystemLoader(PROMPTS_DIR),
        autoescape=select_autoescape(default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("undervalued_commentary.j2")
    return template.render(
        analysis_date=analysis_date.isoformat(),
        strategy_name=strategy_name,
        stocks=[asdict(stock) for stock in stocks],
    )


async def _load_analysis_rows(
    analysis_date: Date,
    strategy_name: str,
    limit: int,
) -> list[BatchAnalysisResult]:
    async with service_session() as session:
        result = await session.execute(
            select(BatchAnalysisResult)
            .where(BatchAnalysisResult.analysis_date == analysis_date)
            .where(BatchAnalysisResult.strategy_name == strategy_name)
            .order_by(BatchAnalysisResult.rank)
            .limit(limit)
        )
        return list(result.scalars())


def _hydrate_stocks(rows: list[BatchAnalysisResult]) -> list[DailyReportStock]:
    if not rows:
        return []

    codes = [row.stock_code for row in rows]
    placeholders = ",".join("?" for _ in codes)
    stock_meta: dict[str, dict[str, Any]] = {}
    with sqlite3.connect(research_db_path) as conn:
        for code, name, sector in conn.execute(
            f"SELECT code, name, sector FROM stocks WHERE code IN ({placeholders})",
            codes,
        ):
            stock_meta[str(code).zfill(6)] = {"name": name, "sector": sector}

    stocks: list[DailyReportStock] = []
    for row in rows:
        meta = stock_meta.get(row.stock_code, {})
        stocks.append(
            DailyReportStock(
                code=row.stock_code,
                name=str(meta.get("name") or row.stock_code),
                sector=meta.get("sector"),
                score=float(row.score),
                rank=int(row.rank),
            )
        )
    return stocks


async def _update_commentary(
    analysis_date: Date,
    strategy_name: str,
    commentary: str,
) -> None:
    async with service_session() as session:
        result = await session.execute(
            select(BatchAnalysisResult)
            .where(BatchAnalysisResult.analysis_date == analysis_date)
            .where(BatchAnalysisResult.strategy_name == strategy_name)
        )
        for row in result.scalars():
            row.llm_commentary = commentary
        await session.commit()


def _fallback_commentary(exc: Exception, stocks: list[DailyReportStock]) -> str:
    if isinstance(exc, LLMError):
        reason = str(exc)
    else:
        reason = f"{exc.__class__.__name__}: {exc}"
    if not stocks:
        return f"LLM commentary unavailable. No analysis rows were found. ({reason})"
    top = ", ".join(f"{stock.code} {stock.name}" for stock in stocks[:3])
    return (
        "LLM commentary unavailable, so this fallback summary was generated locally. "
        f"Top candidates are {top}. Reason: {reason}"
    )


def _telegram_message(
    analysis_date: Date,
    strategy_name: str,
    stocks: list[DailyReportStock],
    commentary: str,
) -> str:
    lines = [
        f"*Daily Report — {analysis_date.isoformat()}*",
        "",
        f"Top Undervalued (strategy: `{strategy_name}`):",
    ]
    if not stocks:
        lines.append("- No candidates found.")
    else:
        for stock in stocks:
            lines.append(
                f"{stock.rank}. `{stock.code}` {stock.name} "
                f"score {stock.score:.4f}"
            )
    trimmed_commentary = commentary[:2500]
    lines.extend(["", "*LLM Commentary:*", trimmed_commentary])
    return "\n".join(lines)


async def _send_daily_report_message(
    analysis_date: Date,
    strategy_name: str,
    stocks: list[DailyReportStock],
    commentary: str,
    *,
    send_telegram: bool,
) -> TelegramSendResult:
    if not send_telegram:
        return TelegramSendResult(
            sent=False,
            skipped=True,
            message="Telegram sending disabled by caller.",
        )

    try:
        return await send_markdown(
            _telegram_message(analysis_date, strategy_name, stocks, commentary)
        )
    except TelegramSendError as exc:
        return TelegramSendResult(
            sent=False,
            skipped=False,
            message=str(exc),
        )
