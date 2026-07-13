"""중간매매 규칙 검증 러너 — baseline 대비 각 규칙의 성과 영향 측정.

승격 방정식(private qlab_alpha_v2)에 규칙을 하나씩(및 콤보로) 붙여
KOSPI200 × (3Y/5Y/FULL)을 돌리고 Sharpe/MDD 변화를 표로 남긴다.
채택 기준: Sharpe 개선, 또는 MDD 개선하면서 Sharpe 유지.

Usage: python research/scripts/validate_rules.py
Output: research/reports/matrix/rules_validation_<ts>/ (results.csv + summary.md)
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.batch.daily_analysis import load_strategy  # noqa: E402
from research.backtest.engine import run_backtest  # noqa: E402

DATA_FLOOR = date(2016, 7, 1)
END_KR = date(2026, 7, 4)
PERIODS = {"3Y": 1095, "5Y": 1825, "FULL": None}

# (변형 이름, StrategyDefinition 오버라이드)
VARIANTS: list[tuple[str, dict]] = [
    ("baseline", {}),
    ("band_trim_1.4", {"band_trim_threshold": 1.4}),
    ("band_trim_1.3", {"band_trim_threshold": 1.3}),
    ("score_exit_0.4", {"replace_if_rank_below": 0.4}),
    ("score_exit_0.3", {"replace_if_rank_below": 0.3}),
    ("stop_-10", {"stop_loss_pct": -0.10}),
    ("stop_-15", {"stop_loss_pct": -0.15}),
    ("tp_+30", {"take_profit_pct": 0.30}),
    ("band1.4+score0.4", {"band_trim_threshold": 1.4, "replace_if_rank_below": 0.4}),
]


def main() -> None:
    base = load_strategy("qlab_alpha_v2")  # private 우선 해석
    out_dir = (
        PROJECT_ROOT / "research" / "reports" / "matrix"
        / f"rules_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for period_name, days in PERIODS.items():
        start = DATA_FLOOR if days is None else max(DATA_FLOOR, END_KR - timedelta(days=days))
        for variant_name, overrides in VARIANTS:
            strategy = base.model_copy(
                update={
                    "name": f"rules_{variant_name}",
                    "start_date": start,
                    "end_date": END_KR,
                    **overrides,
                },
                deep=True,
            )
            result = run_backtest(strategy)
            m = result.metrics
            fired = sum(1 for w in result.warnings if "rule=" in w)
            rows.append({
                "period": period_name,
                "variant": variant_name,
                "total_return": round(result.final_nav / result.initial_nav - 1, 6),
                "cagr": round(m.cagr, 6),
                "mdd": round(m.mdd, 6),
                "sharpe": round(m.sharpe, 4),
                "sortino": round(m.sortino, 4),
                "win_rate": round(m.win_rate, 4),
                "trades": m.n_trades,
                "rule_fires": fired,
            })
            print(
                f"[rules] {period_name}/{variant_name}: ret={rows[-1]['total_return']:+.1%} "
                f"mdd={m.mdd:.1%} sharpe={m.sharpe:.2f} fires={fired}",
                flush=True,
            )

    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    lines = ["# 중간매매 규칙 검증 결과", ""]
    for period_name in PERIODS:
        subset = [r for r in rows if r["period"] == period_name]
        base_row = next(r for r in subset if r["variant"] == "baseline")
        lines += [f"## {period_name} (baseline: sharpe {base_row['sharpe']}, mdd {base_row['mdd']:.1%})", "",
                  "| variant | ret | ΔSharpe | ΔMDD(pp) | fires | trades |", "|---|---|---|---|---|---|"]
        for r in sorted(subset, key=lambda x: x["sharpe"], reverse=True):
            d_sharpe = r["sharpe"] - base_row["sharpe"]
            d_mdd = (r["mdd"] - base_row["mdd"]) * 100
            lines.append(
                f"| {r['variant']} | {r['total_return']:+.1%} | {d_sharpe:+.2f} "
                f"| {d_mdd:+.1f} | {r['rule_fires']} | {r['trades']} |"
            )
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[rules] done → {out_dir}", flush=True)


if __name__ == "__main__":
    main()
