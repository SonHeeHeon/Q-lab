"""Multi-condition backtest matrix — 기간 × 국가 × 유니버스 × 방정식 변형.

Runs every (variant, universe, period) combination, computes absolute AND
benchmark-relative metrics (KOSPI for KR, SP500 for US), and writes
``results.csv`` + a ranked ``summary.md`` under research/reports/matrix/<ts>/.

Usage:
    python research/scripts/run_matrix.py            # full matrix (~1-2h)
    python research/scripts/run_matrix.py --quick    # 1Y smoke subset
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.backtest.benchmark import benchmark_relative, load_benchmark_close
from research.backtest.engine import run_backtest
from shared.domain.strategy import (
    FactorGroup,
    FactorWeight,
    FilterRule,
    GroupFactor,
    StrategyDefinition,
)

MATRIX_ROOT = PROJECT_ROOT / "research" / "reports" / "matrix"

# Data coverage boundaries (see .omc reports 2026-07-07).
DATA_FLOOR = date(2016, 7, 1)
END_KR = date(2026, 7, 4)
END_US = date(2026, 6, 9)  # US prices last synced date

PERIODS: dict[str, int | None] = {
    "3M": 91,
    "6M": 182,
    "1Y": 365,
    "2Y": 730,
    "3Y": 1095,
    "5Y": 1825,
    "FULL": None,  # from DATA_FLOOR
}
# FULL is expensive — run it only for the core variants.
FULL_VARIANTS = {
    "value_v1_flat",
    "v2_base",
    "v2_monthly",
    "v2_regime_monthly",
    "etf_rotation_kr",
    "etf_rotation_us",
}


def _kr_filters() -> list[FilterRule]:
    return [
        FilterRule(field="market_cap", op="GTE", value=1e11),
        FilterRule(field="trading_days_30d", op="GTE", value=25),
    ]


def _groups(value: float, quality: float, momentum: float, flow: float) -> list[FactorGroup]:
    return [
        FactorGroup(name="Value", weight=value, factors=[
            GroupFactor(factor="PER", higher_is_better=False),
            GroupFactor(factor="PBR", higher_is_better=False),
        ]),
        FactorGroup(name="Quality", weight=quality, factors=[
            GroupFactor(factor="ROE"), GroupFactor(factor="ROA"),
        ]),
        FactorGroup(name="Momentum", weight=momentum, factors=[
            GroupFactor(factor="MOMENTUM_3M"), GroupFactor(factor="MOMENTUM_12M"),
        ]),
        FactorGroup(name="Flow", weight=flow, factors=[
            GroupFactor(factor="FOREIGN_NET_20D"), GroupFactor(factor="INST_NET_20D"),
        ]),
    ]


def _base(name: str, universe: str, start: date, end: date, **overrides) -> StrategyDefinition:
    payload = {
        "name": name,
        "description": f"matrix::{name}",
        "universe": universe,
        "rebalance_freq": "QUARTERLY",
        "factors": [],
        "filters": [],
        "top_n": 20,
        "start_date": start,
        "end_date": end,
        "min_groups": 3,
    }
    payload.update(overrides)
    return StrategyDefinition.model_validate(payload)


@dataclass(frozen=True)
class Variant:
    name: str
    country: str  # KR | US
    universes: tuple[str, ...]
    build: "callable"


def _kr_variants() -> list[Variant]:
    def value_v1(u, s, e):
        return _base(
            "value_v1_flat", u, s, e,
            factors=[
                FactorWeight(factor="PER", weight=-1.0, transform="ZSCORE"),
                FactorWeight(factor="PBR", weight=-0.8, transform="ZSCORE"),
                FactorWeight(factor="ROE", weight=1.0, transform="ZSCORE"),
            ],
            filters=_kr_filters(),
        )

    def v2_base(u, s, e):
        return _base("v2_base", u, s, e, groups=_groups(0.30, 0.25, 0.25, 0.20), filters=_kr_filters())

    def v2_value(u, s, e):
        return _base("v2_value_tilt", u, s, e, groups=_groups(0.45, 0.30, 0.15, 0.10), filters=_kr_filters())

    def v2_momflow(u, s, e):
        return _base("v2_mom_flow", u, s, e, groups=_groups(0.15, 0.10, 0.40, 0.35), filters=_kr_filters())

    def v2_monthly(u, s, e):
        return _base(
            "v2_monthly", u, s, e, groups=_groups(0.30, 0.25, 0.25, 0.20),
            filters=_kr_filters(), rebalance_freq="MONTHLY",
        )

    def v2_regime(u, s, e):
        return _base(
            "v2_regime_monthly", u, s, e, groups=_groups(0.30, 0.25, 0.25, 0.20),
            filters=_kr_filters(), use_regime=True, regime_check="MONTHLY",
        )

    def v2_lag1(u, s, e):
        return _base(
            "v2_lag1", u, s, e, groups=_groups(0.30, 0.25, 0.25, 0.20),
            filters=_kr_filters(), execution_lag_days=1,
        )

    unis = ("KOSPI200", "KOSPI_TOP100")
    return [
        Variant("value_v1_flat", "KR", unis, value_v1),
        Variant("v2_base", "KR", unis, v2_base),
        Variant("v2_value_tilt", "KR", unis, v2_value),
        Variant("v2_mom_flow", "KR", unis, v2_momflow),
        Variant("v2_monthly", "KR", unis, v2_monthly),
        Variant("v2_regime_monthly", "KR", unis, v2_regime),
        Variant("v2_lag1", "KR", unis, v2_lag1),
    ]


def _us_variants() -> list[Variant]:
    def us_v2(u, s, e):
        return _base(
            "us_v2", u, s, e, top_n=10, min_groups=2,
            groups=[
                FactorGroup(name="Value", weight=0.3, factors=[
                    GroupFactor(factor="PER", higher_is_better=False),
                    GroupFactor(factor="PBR", higher_is_better=False),
                ]),
                FactorGroup(name="Quality", weight=0.3, factors=[
                    GroupFactor(factor="ROE"), GroupFactor(factor="ROA"),
                ]),
                FactorGroup(name="Momentum", weight=0.4, factors=[
                    GroupFactor(factor="MOMENTUM_3M"), GroupFactor(factor="MOMENTUM_12M"),
                ]),
            ],
        )

    def us_momentum(u, s, e):
        return _base(
            "us_momentum", u, s, e, top_n=10, min_groups=1, rebalance_freq="MONTHLY",
            groups=[FactorGroup(name="Momentum", weight=1.0, factors=[
                GroupFactor(factor="MOMENTUM_3M"), GroupFactor(factor="MOMENTUM_12M"),
            ])],
        )

    return [
        Variant("us_v2", "US", ("NASDAQ100",), us_v2),
        Variant("us_momentum", "US", ("NASDAQ100",), us_momentum),
    ]


def _etf_variants() -> list[Variant]:
    def rotation(name, u):
        def build(_u, s, e):
            return _base(
                name, u, s, e, top_n=3, min_groups=1, rebalance_freq="MONTHLY",
                groups=[FactorGroup(name="Momentum", weight=1.0, factors=[
                    GroupFactor(factor="MOMENTUM_12M"), GroupFactor(factor="MOMENTUM_3M"),
                ])],
            )
        return build

    def rotation_regime(_u, s, e):
        strat = rotation("etf_kr_regime_monthly", "ETF_KR")(_u, s, e)
        return strat.model_copy(
            update={"use_regime": True, "regime_check": "MONTHLY"}, deep=True
        )

    return [
        Variant("etf_rotation_kr", "KR", ("ETF_KR",), rotation("etf_rotation_kr", "ETF_KR")),
        Variant("etf_kr_regime_monthly", "KR", ("ETF_KR",), rotation_regime),
        Variant("etf_rotation_us", "US", ("ETF_US",), rotation("etf_rotation_us", "ETF_US")),
    ]


def _period_bounds(country: str, days: int | None) -> tuple[date, date]:
    end = END_KR if country == "KR" else END_US
    start = DATA_FLOOR if days is None else max(DATA_FLOOR, end - timedelta(days=days))
    return start, end


def run_matrix(*, quick: bool = False) -> Path:
    from datetime import datetime

    out_dir = MATRIX_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    variants = _kr_variants() + _us_variants() + _etf_variants()
    period_items = list(PERIODS.items())
    if quick:
        period_items = [("1Y", PERIODS["1Y"])]
        variants = [v for v in variants if v.name in {"v2_base", "us_momentum", "etf_rotation_kr"}]

    bench_cache: dict[str, "object"] = {}
    rows: list[dict] = []
    total = sum(
        len(v.universes)
        * sum(1 for p, d in period_items if d is not None or v.name in FULL_VARIANTS)
        for v in variants
    )
    done = 0

    for variant in variants:
        for universe in variant.universes:
            for period_name, days in period_items:
                if days is None and variant.name not in FULL_VARIANTS:
                    continue
                start, end = _period_bounds(variant.country, days)
                strategy = variant.build(universe, start, end)
                try:
                    result = run_backtest(strategy)
                except Exception as exc:  # keep the matrix going
                    print(f"[matrix:ERR] {variant.name}/{universe}/{period_name}: {exc}", flush=True)
                    continue
                bench_code = "KOSPI" if variant.country == "KR" else "SP500"
                if bench_code not in bench_cache:
                    bench_cache[bench_code] = load_benchmark_close(
                        bench_code, DATA_FLOOR, max(END_KR, END_US)
                    )
                bench = bench_cache[bench_code]
                window = bench[
                    (bench.index >= str(result.start_date)) & (bench.index <= str(result.end_date))
                ] if len(bench) else bench
                curve = [(p.date, p.nav) for p in result.equity_curve]
                rel = benchmark_relative(curve, window)
                m = result.metrics
                total_return = result.final_nav / result.initial_nav - 1.0
                rows.append({
                    "country": variant.country,
                    "universe": universe,
                    "variant": variant.name,
                    "period": period_name,
                    "start": result.start_date.isoformat(),
                    "end": result.end_date.isoformat(),
                    "total_return": round(total_return, 6),
                    "cagr": round(m.cagr, 6),
                    "mdd": round(m.mdd, 6),
                    "sharpe": round(m.sharpe, 4),
                    "sortino": round(m.sortino, 4),
                    "win_rate": round(m.win_rate, 4),
                    "trades": m.n_trades,
                    "bench_return": round(rel.benchmark_total_return, 6) if rel else None,
                    "excess_return": round(total_return - rel.benchmark_total_return, 6) if rel else None,
                    "alpha_annual": round(rel.alpha_annual, 6) if rel else None,
                    "beta": round(rel.beta, 4) if rel else None,
                    "ir": round(rel.information_ratio, 4) if rel else None,
                    "n_warnings": len(result.warnings),
                })
                done += 1
                print(
                    f"[matrix] {done}/{total} {variant.country}/{universe}/{variant.name}/{period_name}"
                    f" ret={total_return:+.2%} mdd={m.mdd:.2%} sharpe={m.sharpe:.2f}",
                    flush=True,
                )

    _write_outputs(out_dir, rows)
    print(f"[matrix] done → {out_dir}", flush=True)
    return out_dir


def _write_outputs(out_dir: Path, rows: list[dict]) -> None:
    if not rows:
        (out_dir / "summary.md").write_text("no results\n", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with (out_dir / "results.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# 다조건 백테스트 매트릭스 결과",
        "",
        f"- 총 {len(rows)}개 조합 · KR 종료 {END_KR} / US 종료 {END_US} · 데이터 시작 {DATA_FLOOR}",
        "- excess_return = 전략 총수익 − 벤치마크(KOSPI/SP500) 총수익",
        "",
    ]
    for (country, period) in sorted({(r["country"], r["period"]) for r in rows}):
        subset = [r for r in rows if r["country"] == country and r["period"] == period]
        subset.sort(key=lambda r: (r["sharpe"] if r["sharpe"] is not None else -9), reverse=True)
        lines.append(f"## {country} · {period}")
        lines.append("")
        lines.append("| variant | universe | ret | bench | excess | CAGR | MDD | Sharpe | IR | trades |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in subset:
            lines.append(
                f"| {r['variant']} | {r['universe']} | {r['total_return']:+.1%}"
                f" | {('%+.1f%%' % (100*r['bench_return'])) if r['bench_return'] is not None else '—'}"
                f" | {('%+.1f%%' % (100*r['excess_return'])) if r['excess_return'] is not None else '—'}"
                f" | {r['cagr']:+.1%} | {r['mdd']:.1%} | {r['sharpe']:.2f}"
                f" | {r['ir'] if r['ir'] is not None else '—'} | {r['trades']} |"
            )
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the multi-condition backtest matrix.")
    parser.add_argument("--quick", action="store_true", help="1Y smoke subset")
    args = parser.parse_args()
    run_matrix(quick=args.quick)


if __name__ == "__main__":
    main()
