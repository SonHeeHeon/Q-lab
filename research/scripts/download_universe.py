"""CLI for bulk-loading historical research data into research.db."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("MPLCONFIGDIR", str(Path("/private/tmp/qlab-mplconfig")))


def _bootstrap_ssl_certificates() -> None:
    """Point urllib/requests-based loaders at certifi on local Python installs."""

    try:
        import certifi
    except Exception:
        return

    ca_file = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", ca_file)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_file)


_bootstrap_ssl_certificates()

from dotenv import load_dotenv

from research.data_ingestion.delisted_loader import update_delisted
from research.data_ingestion.financial_loader import update_financials
from research.data_ingestion.pykrx_loader import (
    ensure_stock_rows,
    update_market_indices,
    update_prices,
    update_universe,
)
from research.universe.kosdaq150 import get_kosdaq150_async
from research.universe.kospi200 import get_kospi200_async
from shared.db.session import research_engine

SMOKE_FALLBACK_CODES = ["005930", "000660", "005380", "035420", "051910"]


async def async_main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = _parse_args()
    since = args.since or date.today() - timedelta(days=365 * args.years)
    until = args.until or date.today()

    print(f"[phase2] universe={args.universe} since={since} until={until}")

    if args.codes_file is not None:
        codes = _load_codes_file(args.codes_file)
        print(f"[phase2] loaded codes from {args.codes_file}: {len(codes)}")
    else:
        codes = await _resolve_universe(args.universe, as_of=until, since=since)

    if args.max_codes:
        if not codes:
            codes = SMOKE_FALLBACK_CODES.copy()
            print(
                "[phase2:warn] universe lookup returned no codes; "
                "using smoke-test fallback codes"
            )
        codes = codes[: args.max_codes]
        print(f"[phase2] max-codes applied: {len(codes)}")
    elif not codes:
        raise RuntimeError(
            "Universe lookup returned no stock codes. KRX/pykrx may be blocked or "
            "requiring credentials. Retry later, or run a smoke test with --max-codes."
        )
    else:
        print(f"[phase2] resolved codes: {len(codes)}")

    print("[phase2] ensuring stock master rows...")
    result = await ensure_stock_rows(
        codes,
        market=_default_market(args.universe),
        listed_at_default=since,
    )
    print(f"[phase2] {result.name}: rows={result.requested}")

    if not args.skip_delisted:
        print("[phase2] updating delisted stocks...")
        result = await update_delisted(listed_at_default=since)
        print(f"[phase2] delisted rows seen={result.rows_seen} written={result.rows_written}")

    print("[phase2] updating market indices...")
    if args.skip_indices:
        print("[phase2] market indices skipped")
    else:
        for result in await update_market_indices(start=since, end=until):
            print(f"[phase2] {result.name}: rows={result.requested}")

    if not args.skip_prices:
        print("[phase2] downloading daily prices...")
        result = await update_prices(
            codes,
            start=since,
            end=until,
            concurrency=args.price_concurrency,
            sleep_seconds=args.pykrx_sleep,
        )
        print(f"[phase2] {result.name}: rows={result.requested}")

    if not args.skip_financials:
        print("[phase2] downloading DART financials...")
        result = await update_financials(
            codes,
            since_year=since.year,
            until_year=until.year,
            concurrency=args.financial_concurrency,
            sleep_seconds=args.dart_sleep,
        )
        print(
            "[phase2] financial reports requested="
            f"{result.requested_reports} parsed_rows={result.parsed_rows}"
        )

    await research_engine.dispose()
    print("[phase2] done")
    return 0


async def _resolve_universe(
    universe: str,
    *,
    as_of: date,
    since: date,
) -> list[str]:
    universe = universe.upper()
    if universe == "KOSPI200":
        codes = await get_kospi200_async(as_of)
        await ensure_stock_rows(codes, market="KOSPI", listed_at_default=since)
        return codes

    if universe == "KOSDAQ150":
        codes = await get_kosdaq150_async(as_of)
        await ensure_stock_rows(codes, market="KOSDAQ", listed_at_default=since)
        return codes

    if universe == "KOSPI_ALL":
        await update_universe("KOSPI", as_of=as_of, listed_at_default=since)
        from pykrx import stock

        return sorted(stock.get_market_ticker_list(as_of.strftime("%Y%m%d"), "KOSPI"))

    if universe == "KOSDAQ_ALL":
        await update_universe("KOSDAQ", as_of=as_of, listed_at_default=since)
        from pykrx import stock

        return sorted(stock.get_market_ticker_list(as_of.strftime("%Y%m%d"), "KOSDAQ"))

    raise ValueError(f"Unsupported universe: {universe}")


def _default_market(universe: str) -> str:
    if universe.upper() in {"KOSDAQ150", "KOSDAQ_ALL"}:
        return "KOSDAQ"
    return "KOSPI"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download KRX/DART historical data into research.db."
    )
    parser.add_argument(
        "--universe",
        choices=["KOSPI200", "KOSDAQ150", "KOSPI_ALL", "KOSDAQ_ALL"],
        default="KOSPI200",
    )
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--since", type=_date, default=None)
    parser.add_argument("--until", type=_date, default=None)
    parser.add_argument("--max-codes", type=int, default=0)
    parser.add_argument("--price-concurrency", type=int, default=4)
    parser.add_argument("--financial-concurrency", type=int, default=2)
    parser.add_argument("--pykrx-sleep", type=float, default=0.15)
    parser.add_argument("--dart-sleep", type=float, default=0.2)
    parser.add_argument(
        "--codes-file",
        type=Path,
        default=None,
        help=(
            "Optional CSV/TXT file containing stock codes. Use this when KRX "
            "universe endpoints are unavailable."
        ),
    )
    parser.add_argument("--skip-delisted", action="store_true")
    parser.add_argument("--skip-indices", action="store_true")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--skip-financials", action="store_true")
    return parser.parse_args()


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _load_codes_file(path: Path) -> list[str]:
    resolved = path if path.is_absolute() else PROJECT_ROOT / path
    text = resolved.read_text(encoding="utf-8-sig")
    codes = sorted(dict.fromkeys(re.findall(r"(?<!\d)\d{6}(?!\d)", text)))
    if not codes:
        raise RuntimeError(f"No six-digit stock codes found in {resolved}")
    return codes


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
