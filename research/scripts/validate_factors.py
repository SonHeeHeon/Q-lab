"""팩터 확장 검증 러너 — 승격 방정식에 후보 팩터를 하나씩 붙여 OOS로 검증.

Phase 4.3. 각 후보를 승격 설정(private qlab_alpha_v2 + band_trim_1.4)에 추가/교체한
변형을 만들고 KOSPI200 × (3Y/5Y/FULL) 백테스트 + walk-forward OOS(train 4y/test 1y,
가중치 재튜닝 없음)로 비교한다.

채택 기준: OOS Sharpe 개선, 또는 MDD 개선하면서 Sharpe 유지 — 전 구간 일관.
다중검정 인식: summary.md 하단에 '시도 횟수 장부'를 남긴다(Bailey-López de Prado MinBTL 취지).

Usage:
    python research/scripts/validate_factors.py [a|b|c|all]   # 기본 all(구현된 것만)
Output: research/reports/matrix/factor_validation_<ts>/{results.csv, summary.md}
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.batch.daily_analysis import load_strategy  # noqa: E402
from research.backtest.engine import run_backtest  # noqa: E402
from research.backtest.walk_forward import walk_forward  # noqa: E402
from shared.domain.strategy import FactorGroup, GroupFactor  # noqa: E402

DATA_FLOOR = date(2016, 7, 1)
END_KR = date(2026, 7, 4)
PERIODS = {"3Y": 1095, "5Y": 1825, "FULL": None}
WF_TRAIN_YEARS = 4
WF_TEST_YEARS = 1


def _add_factor(groups: list[FactorGroup], group_name: str, factor: GroupFactor) -> list[FactorGroup]:
    """지정 그룹에 팩터를 추가한 새 그룹 리스트(깊은 복사)."""
    out: list[FactorGroup] = []
    for g in groups:
        gc = g.model_copy(deep=True)
        if gc.name == group_name:
            gc.factors = [*gc.factors, factor.model_copy(deep=True)]
        out.append(gc)
    return out


def _replace_factors(groups: list[FactorGroup], group_name: str, factors: list[GroupFactor]) -> list[FactorGroup]:
    """지정 그룹의 팩터 전체를 교체(같은 테마 중복 방지용)."""
    out: list[FactorGroup] = []
    for g in groups:
        gc = g.model_copy(deep=True)
        if gc.name == group_name:
            gc.factors = [f.model_copy(deep=True) for f in factors]
        out.append(gc)
    return out


# (후보키, 변형이름, groups 변환 함수). baseline은 항상 포함.
# 구현된 팩터만 등록 — B/C는 팩터 구현 후 아래에 추가한다.
def _variants(candidate: str) -> list[tuple[str, object]]:
    variants: list[tuple[str, object]] = [("baseline", lambda gs: [g.model_copy(deep=True) for g in gs])]
    if candidate in ("a", "all"):
        # A: 개인 수급 역신호를 Flow 그룹에 추가.
        variants.append(
            ("indiv_flow", lambda gs: _add_factor(
                gs, "Flow", GroupFactor(factor="INDIV_NET_20D", higher_is_better=False)))
        )
    if candidate in ("b", "all"):
        # B: 기존 Value/Quality 그룹을 측정치로 두껍게 (PSR, OP_MARGIN).
        variants.append(("psr", lambda gs: _add_factor(
            gs, "Value", GroupFactor(factor="PSR", higher_is_better=False))))
        variants.append(("op_margin", lambda gs: _add_factor(
            gs, "Quality", GroupFactor(factor="OP_MARGIN", higher_is_better=True))))
        variants.append(("psr+op_margin", lambda gs: _add_factor(
            _add_factor(gs, "Value", GroupFactor(factor="PSR", higher_is_better=False)),
            "Quality", GroupFactor(factor="OP_MARGIN", higher_is_better=True))))
    if candidate in ("c", "all"):
        # C: Momentum 그룹을 잔차(시장조정) 모멘텀으로 교체.
        variants.append(("idio_mom", lambda gs: _replace_factors(
            gs, "Momentum", [
                GroupFactor(factor="IDIO_MOM_3M", higher_is_better=True),
                GroupFactor(factor="IDIO_MOM_12M", higher_is_better=True),
            ])))
    return variants


MIN_FOLD_DAYS = 300  # 말단 stub fold(수일짜리) 제외 — Sharpe 연율화가 폭주함


def _oos_metrics(strategy) -> tuple[float, float, int]:
    """walk-forward OOS: fold별 Sharpe/MDD 평균 + 유효 fold 수. 재튜닝 없음(팩터 유무만 비교).

    walk_forward는 test_end를 strategy.end_date로 clip하면서 항상 마지막에 수일짜리
    stub fold를 만든다. 그 창의 연율화 Sharpe(±수십)가 평균을 오염시키므로 300일 미만
    fold는 버린다.
    """
    wf = walk_forward(
        strategy, train_years=WF_TRAIN_YEARS, test_years=WF_TEST_YEARS, step_years=1,
    )
    pairs = [
        (w, r) for w, r in zip(wf.windows, wf.results)
        if (w.test_end - w.test_start).days >= MIN_FOLD_DAYS
    ]
    if not pairs:
        return float("nan"), float("nan"), 0
    sharpes = [r.metrics.sharpe for _, r in pairs]
    mdds = [r.metrics.mdd for _, r in pairs]
    return mean(sharpes), mean(mdds), len(sharpes)


def main() -> None:
    candidate = (sys.argv[1].lower() if len(sys.argv) > 1 else "all")
    base = load_strategy("qlab_alpha_v2")  # private 우선 (band_trim_1.4 포함)
    if not base.groups:
        raise SystemExit("qlab_alpha_v2 must be a grouped strategy")
    variants = _variants(candidate)

    out_dir = (
        PROJECT_ROOT / "research" / "reports" / "matrix"
        / f"factor_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for period_name, days in PERIODS.items():
        start = DATA_FLOOR if days is None else max(DATA_FLOOR, END_KR - timedelta(days=days))
        for variant_name, transform in variants:
            groups = transform(base.groups)
            strategy = base.model_copy(
                update={
                    "name": f"factor_{variant_name}",
                    "start_date": start,
                    "end_date": END_KR,
                    "groups": groups,
                },
                deep=True,
            )
            result = run_backtest(strategy)
            m = result.metrics
            # OOS는 전체 데이터가 필요하므로 FULL 구간에서만 walk-forward 수행.
            if period_name == "FULL":
                oos_sharpe, oos_mdd, folds = _oos_metrics(strategy)
            else:
                oos_sharpe, oos_mdd, folds = float("nan"), float("nan"), 0
            rows.append({
                "period": period_name,
                "variant": variant_name,
                "total_return": round(result.final_nav / result.initial_nav - 1, 6),
                "cagr": round(m.cagr, 6),
                "mdd": round(m.mdd, 6),
                "sharpe": round(m.sharpe, 4),
                "oos_sharpe": round(oos_sharpe, 4) if folds else "",
                "oos_mdd": round(oos_mdd, 6) if folds else "",
                "oos_folds": folds,
                "trades": m.n_trades,
            })
            oos_str = f" oos_sharpe={oos_sharpe:.2f}({folds}f)" if folds else ""
            print(
                f"[factor] {period_name}/{variant_name}: ret={rows[-1]['total_return']:+.1%} "
                f"mdd={m.mdd:.1%} sharpe={m.sharpe:.2f}{oos_str}",
                flush=True,
            )

    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    lines = ["# 팩터 확장 검증 결과", "", f"후보: `{candidate}`", ""]
    for period_name in PERIODS:
        subset = [r for r in rows if r["period"] == period_name]
        base_row = next(r for r in subset if r["variant"] == "baseline")
        header = f"## {period_name} (baseline: sharpe {base_row['sharpe']}, mdd {base_row['mdd']:.1%}"
        if base_row["oos_folds"]:
            header += f", OOS sharpe {base_row['oos_sharpe']} / {base_row['oos_folds']}folds"
        header += ")"
        lines += [header, "",
                  "| variant | ret | ΔSharpe | ΔMDD(pp) | ΔOOS_Sharpe | trades |",
                  "|---|---|---|---|---|---|"]
        for r in sorted(subset, key=lambda x: x["sharpe"], reverse=True):
            d_sharpe = r["sharpe"] - base_row["sharpe"]
            d_mdd = (r["mdd"] - base_row["mdd"]) * 100
            if r["oos_folds"] and base_row["oos_folds"]:
                d_oos = f"{r['oos_sharpe'] - base_row['oos_sharpe']:+.2f}"
            else:
                d_oos = "—"
            lines.append(
                f"| {r['variant']} | {r['total_return']:+.1%} | {d_sharpe:+.2f} "
                f"| {d_mdd:+.1f} | {d_oos} | {r['trades']} |"
            )
        lines.append("")

    # 시도 횟수 장부 (다중검정 인식).
    tried = len(variants) - 1  # baseline 제외
    lines += [
        "## 시도 횟수 장부 (다중검정 인식)",
        "",
        f"- 이번 실행에서 시험한 후보 변형: **{tried}개** (baseline 제외)",
        "- 채택 기준: OOS Sharpe 개선, 또는 MDD 개선∧Sharpe 유지 — 3Y/5Y/FULL 전 구간 일관.",
        "- 과적합 방어: 변형을 많이 시험할수록 최고 성과가 우연히 부풀려짐(Bailey-López de Prado). "
        "OOS(walk-forward) 열을 1차 근거로 삼고, IS(3Y/5Y/FULL) 개선만으로는 채택하지 않는다.",
        "",
    ]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[factor] done → {out_dir}", flush=True)


if __name__ == "__main__":
    main()
