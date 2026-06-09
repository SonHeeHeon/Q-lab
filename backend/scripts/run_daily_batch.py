"""Run the daily analysis + LLM commentary + Telegram report once."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date as Date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.batch.daily_analysis import run_daily_analysis
from backend.app.services.batch.daily_report import run_daily_report
from shared.db.session import research_engine, service_engine


async def async_main() -> int:
    args = _parse_args()
    analysis_date = Date.fromisoformat(args.date) if args.date else None

    analysis = await run_daily_analysis(
        analysis_date=analysis_date,
        strategy_name=args.strategy,
        limit=args.limit,
    )
    print(
        "[daily-batch] analysis "
        f"date={analysis.analysis_date} strategy={analysis.strategy_name} "
        f"rows={len(analysis.rows)}"
    )
    for row in analysis.rows:
        print(
            "[daily-batch] "
            f"rank={row.rank} code={row.stock_code} score={row.score:.6f}"
        )

    report = await run_daily_report(
        analysis_date=analysis.analysis_date,
        strategy_name=analysis.strategy_name,
        limit=args.limit,
        send_telegram=not args.skip_telegram,
        strict_llm=args.strict_llm,
    )
    print(
        "[daily-batch] report "
        f"stocks={len(report.stocks)} llm_fallback={report.llm_fallback_used} "
        f"telegram_sent={report.telegram.sent} "
        f"telegram_skipped={report.telegram.skipped}"
    )
    print(f"[daily-batch] telegram_message={report.telegram.message}")
    print("[daily-batch] done")

    await service_engine.dispose()
    await research_engine.dispose()
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Q-Lab daily batch once.")
    parser.add_argument("--date", default=None, help="Analysis date, YYYY-MM-DD.")
    parser.add_argument("--strategy", default=None, help="Strategy name, e.g. value_v1.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--skip-telegram",
        action="store_true",
        help="Compute commentary but do not send Telegram.",
    )
    parser.add_argument(
        "--strict-llm",
        action="store_true",
        help="Fail instead of using fallback commentary when LLM call fails.",
    )
    return parser.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
