"""Layer B(매크로 레짐 게이트) 활성화 검증 러너 — 기간별로 켜는 게 나은지 판정.

승격 방정식(private qlab_alpha_v2, band_trim_1.4)을 그대로 두고 use_regime 만 토글:
  baseline          : use_regime=False (항상 100% 투자 — 현행)
  regime_rebalance  : use_regime=True, regime_check=REBALANCE (리밸런스일에만 레짐 샘플)
  regime_monthly    : use_regime=True, regime_check=MONTHLY   (월초 추가 확인 + 5일 확정)

기간: 1Y/2Y/3Y/5Y. "어떤 기간엔 어떤 게 더 좋은지"를 표 + 기간별 승자로 답한다.
레짐은 하락장 방어(노출 축소)라 상승장에선 수익을 희생하고 하락 구간에선 MDD를 줄인다 —
기간마다 국면 구성이 달라 결과가 갈리는 게 정상. 정직하게 기록한다.

Usage: python research/scripts/validate_regime.py
Output: research/reports/matrix/regime_validation_<ts>/{results.csv, summary.md}
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
PERIODS = {"1Y": 365, "2Y": 730, "3Y": 1095, "5Y": 1825}

VARIANTS: list[tuple[str, dict]] = [
    ("baseline", {"use_regime": False}),
    ("regime_rebalance", {"use_regime": True, "regime_check": "REBALANCE"}),
    ("regime_monthly", {"use_regime": True, "regime_check": "MONTHLY"}),
]


def main() -> None:
    base = load_strategy("qlab_alpha_v2")  # private 우선 (band_trim_1.4 포함)
    out_dir = (
        PROJECT_ROOT / "research" / "reports" / "matrix"
        / f"regime_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for period_name, days in PERIODS.items():
        start = max(DATA_FLOOR, END_KR - timedelta(days=days))
        for variant_name, overrides in VARIANTS:
            strategy = base.model_copy(
                update={
                    "name": f"regime_{variant_name}",
                    "start_date": start,
                    "end_date": END_KR,
                    **overrides,
                },
                deep=True,
            )
            result = run_backtest(strategy)
            m = result.metrics
            regime_events = sum(1 for w in result.warnings if "regime-adjust" in w)
            rows.append({
                "period": period_name,
                "variant": variant_name,
                "total_return": round(result.final_nav / result.initial_nav - 1, 6),
                "cagr": round(m.cagr, 6),
                "mdd": round(m.mdd, 6),
                "sharpe": round(m.sharpe, 4),
                "sortino": round(m.sortino, 4),
                "regime_events": regime_events,
                "trades": m.n_trades,
            })
            print(
                f"[regime] {period_name}/{variant_name}: ret={rows[-1]['total_return']:+.1%} "
                f"mdd={m.mdd:.1%} sharpe={m.sharpe:.2f} regime_events={regime_events}",
                flush=True,
            )

    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    lines = ["# Layer B(레짐 게이트) 활성화 검증 — 기간별", "",
             "레짐 ON = 하락장 방어(노출 100/70/40/0%). 상승장 수익 희생 ↔ 하락장 MDD 축소.", ""]
    verdicts: list[str] = []
    for period_name in PERIODS:
        subset = [r for r in rows if r["period"] == period_name]
        base_row = next(r for r in subset if r["variant"] == "baseline")
        lines += [
            f"## {period_name} (baseline: sharpe {base_row['sharpe']}, mdd {base_row['mdd']:.1%})",
            "",
            "| variant | ret | ΔSharpe | ΔMDD(pp) | sortino | regime_events |",
            "|---|---|---|---|---|---|",
        ]
        for r in sorted(subset, key=lambda x: x["sharpe"], reverse=True):
            d_sharpe = r["sharpe"] - base_row["sharpe"]
            d_mdd = (r["mdd"] - base_row["mdd"]) * 100  # 양수=개선
            lines.append(
                f"| {r['variant']} | {r['total_return']:+.1%} | {d_sharpe:+.2f} "
                f"| {d_mdd:+.1f} | {r['sortino']:.2f} | {r['regime_events']} |"
            )
        lines.append("")
        # 기간별 승자 판정
        best_sharpe = max(subset, key=lambda x: x["sharpe"])
        best_mdd = max(subset, key=lambda x: x["mdd"])  # mdd는 음수라 max=가장 얕음
        verdicts.append(
            f"- **{period_name}**: 최고 Sharpe = `{best_sharpe['variant']}` "
            f"({best_sharpe['sharpe']}), 최저 MDD = `{best_mdd['variant']}` "
            f"({best_mdd['mdd']:.1%})"
        )

    lines += ["## 기간별 승자 요약", ""] + verdicts + [
        "",
        "## 채택 기준",
        "- 레짐 ON은 '알파'가 아니라 '방어'. Sharpe 개선 또는 MDD 큰 개선∧Sharpe 유지면 해당 국면에 유효.",
        "- 기간마다 국면 구성이 달라 결과가 갈리는 게 정상 — 단일 정답 아님. "
        "사용자 위험선호(상승 수익 vs 하락 방어)에 따라 프리셋 선택.",
        "",
    ]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[regime] done → {out_dir}", flush=True)


if __name__ == "__main__":
    main()
