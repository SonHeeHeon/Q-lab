"""절대 모멘텀 게이트(abs_momentum_gate) 활성화 검증 러너 — 기간별 + walk-forward OOS.

etf_rotation_kr(공개)을 그대로 두고 abs_momentum_gate 만 토글:
  baseline : abs_momentum_gate=False (항상 top_n 보유 — 현행)
  gated    : abs_momentum_gate=True  (자기 12M 모멘텀<=0 종목 제외, 빈 슬롯은 현금)

게이트는 '알파'가 아니라 '하락장 방어'(GEM식 절대 모멘텀)다. 상승장에선 현금 비중으로
수익을 희생하고 하락장에선 MDD를 줄인다 — 기간마다 국면 구성이 달라 결과가 갈리는 게 정상.

⚠️⚠️ 이 개발 샌드박스는 최근 구간 시세가 **합성(mock 네트워크·가짜 2026 시계)**이라
여기서 나온 수치는 **채택 근거가 아니다**. 반드시 **실환경(실 시계·실 KRX 데이터)**에서
다시 돌려 walk-forward OOS로 판정한 뒤에만 게이트를 켠다(게이트는 OFF로 출하됨).

Usage:
  python research/scripts/validate_absmom.py [--strategy etf_rotation_kr] [--periods 1Y 3Y 5Y FULL]
Output: research/reports/matrix/absmom_validation_<ts>/{results.csv, summary.md}
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.batch.daily_analysis import load_strategy  # noqa: E402
from research.backtest.engine import run_backtest  # noqa: E402

try:
    from research.backtest.walk_forward import walk_forward  # noqa: E402
    _HAS_WF = True
except Exception:  # pragma: no cover - walk_forward optional
    _HAS_WF = False

DATA_FLOOR = date(2016, 7, 1)
END_KR = date(2026, 7, 4)
PERIOD_DAYS = {"1Y": 365, "2Y": 730, "3Y": 1095, "5Y": 1825, "FULL": None}

VARIANTS: list[tuple[str, dict]] = [
    ("baseline", {"abs_momentum_gate": False}),
    ("gated", {"abs_momentum_gate": True}),
]

SYNTH_WARNING = (
    "⚠️ 이 실행 환경이 합성 데이터(mock 네트워크·가짜 시계)라면 아래 수치는 "
    "설명용일 뿐 채택 근거가 아니다. 실환경에서 다시 검증할 것."
)


def _variant_strategy(base, variant_name: str, overrides: dict, start: date):
    return base.model_copy(
        update={
            "name": f"absmom_{variant_name}",
            "start_date": start,
            "end_date": END_KR,
            **overrides,
        },
        deep=True,
    )


def _in_sample_rows(base, periods: list[str]) -> list[dict]:
    rows: list[dict] = []
    for period_name in periods:
        days = PERIOD_DAYS[period_name]
        start = DATA_FLOOR if days is None else max(DATA_FLOOR, END_KR - timedelta(days=days))
        for variant_name, overrides in VARIANTS:
            strategy = _variant_strategy(base, variant_name, overrides, start)
            try:
                result = run_backtest(strategy)
            except Exception as exc:  # noqa: BLE001 - one bad period must not kill the matrix
                print(f"[absmom] {period_name}/{variant_name} FAILED: {exc}", flush=True)
                continue
            m = result.metrics
            # 게이트 발동 근사치: 모멘텀 관련 경고 수(엔진이 남기면). 없으면 0.
            gate_events = sum(1 for w in result.warnings if "momentum" in w.lower())
            rows.append({
                "period": period_name,
                "variant": variant_name,
                "total_return": round(result.final_nav / result.initial_nav - 1, 6),
                "cagr": round(m.cagr, 6),
                "mdd": round(m.mdd, 6),
                "sharpe": round(m.sharpe, 4),
                "sortino": round(m.sortino, 4),
                "gate_events": gate_events,
                "trades": m.n_trades,
            })
            print(
                f"[absmom] {period_name}/{variant_name}: ret={rows[-1]['total_return']:+.1%} "
                f"mdd={m.mdd:.1%} sharpe={m.sharpe:.2f} gate_events={gate_events}",
                flush=True,
            )
    return rows


def _oos_rows(base) -> list[dict]:
    """walk_forward OOS: 변형별 fold 평균 Sharpe/MDD (train 5y/test 1y)."""
    if not _HAS_WF:
        return []
    rows: list[dict] = []
    for variant_name, overrides in VARIANTS:
        strategy = _variant_strategy(base, variant_name, overrides, DATA_FLOOR)
        try:
            wf = walk_forward(strategy, train_years=5, test_years=1, optimize_trials=0)
            fold_results = wf.results
            if not fold_results:
                continue
            mean_sharpe = sum(r.metrics.sharpe for r in fold_results) / len(fold_results)
            mean_mdd = sum(r.metrics.mdd for r in fold_results) / len(fold_results)
            rows.append({
                "variant": variant_name,
                "folds": len(fold_results),
                "oos_sharpe": round(mean_sharpe, 4),
                "oos_mdd": round(mean_mdd, 6),
            })
            print(
                f"[absmom] OOS {variant_name}: folds={len(fold_results)} "
                f"sharpe={mean_sharpe:.2f} mdd={mean_mdd:.1%}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[absmom] OOS {variant_name} FAILED: {exc}", flush=True)
    return rows


def _write_summary(out_dir: Path, rows: list[dict], oos: list[dict], periods: list[str]) -> None:
    lines = [
        "# 절대 모멘텀 게이트 활성화 검증 — 기간별 + walk-forward OOS",
        "",
        f"> {SYNTH_WARNING}",
        "",
        "게이트 ON = 자기 12M 모멘텀<=0 종목 제외(빈 슬롯 현금). 하락장 방어 ↔ 상승장 수익 희생.",
        "",
    ]
    verdicts: list[str] = []
    for period_name in periods:
        subset = [r for r in rows if r["period"] == period_name]
        base_row = next((r for r in subset if r["variant"] == "baseline"), None)
        if base_row is None:
            continue
        lines += [
            f"## {period_name} (baseline: sharpe {base_row['sharpe']}, mdd {base_row['mdd']:.1%})",
            "",
            "| variant | ret | ΔSharpe | ΔMDD(pp) | sortino | gate_events |",
            "|---|---|---|---|---|---|",
        ]
        for r in sorted(subset, key=lambda x: x["sharpe"], reverse=True):
            d_sharpe = r["sharpe"] - base_row["sharpe"]
            d_mdd = (r["mdd"] - base_row["mdd"]) * 100  # 양수=개선
            lines.append(
                f"| {r['variant']} | {r['total_return']:+.1%} | {d_sharpe:+.2f} "
                f"| {d_mdd:+.1f} | {r['sortino']:.2f} | {r['gate_events']} |"
            )
        lines.append("")
        gated = next((r for r in subset if r["variant"] == "gated"), None)
        if gated is not None:
            improves_sharpe = gated["sharpe"] > base_row["sharpe"]
            improves_mdd = gated["mdd"] > base_row["mdd"]  # mdd 음수 → 큰 값=얕음=개선
            holds_sharpe = gated["sharpe"] >= base_row["sharpe"] - 0.05
            adopt = improves_sharpe or (improves_mdd and holds_sharpe)
            verdicts.append(
                f"- **{period_name}**: 게이트 {'채택 후보' if adopt else '미채택'} "
                f"(ΔSharpe {gated['sharpe']-base_row['sharpe']:+.2f}, "
                f"ΔMDD {(gated['mdd']-base_row['mdd'])*100:+.1f}pp)"
            )

    if oos:
        lines += ["## walk-forward OOS (train 5y / test 1y, fold 평균)", "",
                  "| variant | folds | OOS Sharpe | OOS MDD |", "|---|---|---|---|"]
        for r in oos:
            lines.append(
                f"| {r['variant']} | {r['folds']} | {r['oos_sharpe']} | {r['oos_mdd']:.1%} |"
            )
        lines.append("")

    lines += ["## 기간별 판정(인-샘플)", ""] + verdicts + [
        "",
        "## 채택 기준 (게이트는 방어용)",
        "- Sharpe 개선 **또는** MDD 큰 개선∧Sharpe 유지면 해당 국면에 유효.",
        "- **인-샘플은 참고용**. 실제 채택은 위 walk-forward **OOS**에서 baseline 대비 개선이 "
        "일관될 때만. 그리고 반드시 **실환경(실데이터)**에서 재확인.",
        f"- {SYNTH_WARNING}",
        "",
    ]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(description="절대 모멘텀 게이트 검증 러너")
    parser.add_argument("--strategy", default="etf_rotation_kr")
    parser.add_argument("--periods", nargs="+", default=["1Y", "3Y", "5Y", "FULL"],
                        choices=list(PERIOD_DAYS.keys()))
    parser.add_argument("--no-oos", action="store_true", help="walk-forward OOS 생략")
    parser.add_argument("--stamp", default=None, help="출력 폴더 타임스탬프(미지정 시 now)")
    args = parser.parse_args(argv)

    print(f"\n{'='*70}\n{SYNTH_WARNING}\n{'='*70}\n", flush=True)

    base = load_strategy(args.strategy)
    stamp = args.stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "research" / "reports" / "matrix" / f"absmom_validation_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _in_sample_rows(base, args.periods)
    oos = [] if args.no_oos else _oos_rows(base)

    if rows:
        with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    _write_summary(out_dir, rows, oos, args.periods)
    print(f"[absmom] done → {out_dir}", flush=True)
    return out_dir


if __name__ == "__main__":
    main()
