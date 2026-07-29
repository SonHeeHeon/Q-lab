"""개인 계좌 4슬리브 최적 비중 탐색 — 세후 + 원화(KRW) 관점.

4개 채택 방정식(private 우선: qlab_alpha_v2 / etf_rotation_kr / us_value /
etf_rotation_us)을 공통 구간(2016-07~2026-07)에서 세후로 돌리고, US 슬리브는
USDKRW를 반영해 원화 투자자 관점 곡선으로 환산한 뒤:

  1) 슬리브 단독 성과  2) 균등(25×4) 기준선  3) 인샘플 Optuna 최적(탐색용)
  4) walk-forward OOS 최적(채택 근거)  5) 세 비중의 전체 구간 비교

를 산출한다. 인샘플 비중은 과적합 가능성이 있어 채택 근거는 항상 OOS.

Usage: python research/scripts/optimize_sleeve_mix.py [--trials 300]
Output: research/reports/matrix/sleeve_mix_<ts>/ (results.md + weights.csv)
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import optuna  # noqa: E402

from backend.app.services.batch.daily_analysis import load_strategy  # noqa: E402
from research.backtest.engine import run_backtest  # noqa: E402
from research.backtest.metrics import compute_metrics  # noqa: E402
from research.backtest.portfolio import (  # noqa: E402
    _usdkrw_index,
    apply_krw_view,
    blend_curves,
    normalize_curve,
    optimize_sleeve_weights_oos,
)
from research.backtest.tax_kr import default_tax_model_for_universe  # noqa: E402

SLEEVES = [
    ("KR주식", "qlab_alpha_v2"),
    ("KR_ETF", "etf_rotation_kr"),
    ("US주식", "us_value"),
    ("US_ETF", "etf_rotation_us"),
]


def _metrics_of(curve_points: list) -> dict:
    m = compute_metrics(curve_points, [])
    calmar = m.cagr / abs(m.mdd) if m.mdd else 0.0
    return {"cagr": round(m.cagr, 4), "mdd": round(m.mdd, 4),
            "sharpe": round(m.sharpe, 3), "calmar": round(calmar, 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=300)
    parser.add_argument("--max-weight", type=float, default=None,
                        help="슬리브 집중 상한(예: 0.5) — 무제약 쏠림의 실용 대안")
    parser.add_argument("--skip-oos", action="store_true")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2016, 7, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--eval-weights", default=None,
                        help="쉼표 4비중(예: 0.1,0,0.5,0.4) — 지정 비중 평가 행 추가")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "research" / "reports" / "matrix" / f"sleeve_mix_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    fx = _usdkrw_index(None)
    if fx.empty:
        raise SystemExit("USDKRW 없음 — KRW 관점 불가")

    # 1) 4슬리브 세후 백테스트 1회(곡선 캐시) + KRW 환산
    strategies = []
    curves = []
    solo_rows = []
    for label, name in SLEEVES:
        strat = load_strategy(name).model_copy(
            update={"start_date": args.start, "end_date": args.end}
        )
        strategies.append(strat)
        result = run_backtest(
            strat, tax_model=default_tax_model_for_universe(strat.universe)
        )
        curve = apply_krw_view(
            normalize_curve(result.equity_curve), strat.universe, fx
        )
        curves.append(curve)
        pts = [(idx.date(), float(v)) for idx, v in curve.items()]
        solo_rows.append({"sleeve": label, "strategy": name, **_metrics_of(pts)})
        print(f"[mix] solo {label}({name}): {solo_rows[-1]}", flush=True)

    def blended_metrics(weights: list[float]) -> dict:
        pts = blend_curves(curves, weights, rebalance="QUARTERLY")
        return _metrics_of(pts)

    # 2) 균등 기준선
    equal = blended_metrics([0.25] * 4)
    print(f"[mix] equal 25x4: {equal}", flush=True)

    # 3) 인샘플 Optuna(캐시 곡선 재합성 — 저렴)
    def objective(trial: optuna.Trial) -> float:
        w = [trial.suggest_float(f"w_{i}", 0.0, 1.0) for i in range(4)]
        if sum(w) <= 0:
            return -1e9
        norm = [x / sum(w) for x in w]
        if args.max_weight is not None and max(norm) > args.max_weight + 1e-9:
            return -1e9
        m = blended_metrics(w)
        return m["calmar"] if math.isfinite(m["calmar"]) else -1e9

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=42)
    )
    study.optimize(objective, n_trials=args.trials)
    raw = [study.best_params[f"w_{i}"] for i in range(4)]
    insample_w = [x / sum(raw) for x in raw]
    insample = blended_metrics(insample_w)
    print(f"[mix] insample w={[round(x,3) for x in insample_w]}: {insample}", flush=True)

    # 지정 비중 평가(예: 사용자 확정 비중) — 탐색이 아니라 단순 합성 측정
    eval_w: list[float] | None = None
    eval_m: dict | None = None
    if args.eval_weights:
        eval_w = [float(x) for x in args.eval_weights.split(",")]
        if len(eval_w) != 4:
            raise SystemExit("--eval-weights는 4개 비중이어야 함")
        eval_m = blended_metrics(eval_w)
        print(f"[mix] eval w={eval_w}: {eval_m}", flush=True)

    # 4) OOS(rolling 5Y train / 1Y test — 채택 근거)
    oos: dict = {"weights": None}
    if not args.skip_oos:
        oos = optimize_sleeve_weights_oos(
            strategies, train_years=5, test_years=1, objective="calmar",
            trials=150, after_tax=True, krw_view=True,
            max_weight=args.max_weight,
        )
        print(f"[mix] OOS w={[round(x,3) for x in oos['weights']]}"
              f" folds={oos['folds']} oos_calmar_mean={oos['oos_metric_mean']:.3f}",
              flush=True)

    # 5) 비교표 + 저장
    lines = ["# 개인 계좌 4슬리브 최적 비중 (세후·KRW 관점)", "",
             f"- 구간: {args.start} ~ {args.end} · 분기 리밸런스 · 목적 Calmar",
             "- 세후: KR 과세 ETF 15.4% per-sell + US 양도세 연간통산(공제 250만, 22%)",
             "- KRW 관점: US 슬리브 곡선에 USDKRW 반영(환수익 포함)", "",
             "## 슬리브 단독 (세후·KRW)",
             "| 슬리브 | 전략 | CAGR | MDD | Sharpe | Calmar |", "|---|---|---|---|---|---|"]
    for r in solo_rows:
        lines.append(f"| {r['sleeve']} | {r['strategy']} | {r['cagr']} | {r['mdd']} |"
                     f" {r['sharpe']} | {r['calmar']} |")
    lines += ["", "## 비중 비교 (전체 구간 합성)",
              "| 비중 | " + " | ".join(l for l, _ in SLEEVES) + " | CAGR | MDD | Sharpe | Calmar |",
              "|---|---|---|---|---|---|---|---|---|"]

    def _row(name: str, w: list[float], m: dict) -> str:
        ws = " | ".join(f"{x:.0%}" for x in w)
        return f"| {name} | {ws} | {m['cagr']} | {m['mdd']} | {m['sharpe']} | {m['calmar']} |"

    lines.append(_row("균등", [0.25] * 4, equal))
    lines.append(_row("인샘플 최적(참고)", insample_w, insample))
    if eval_w is not None and eval_m is not None:
        lines.append(_row("지정 비중", eval_w, eval_m))
    if oos.get("weights"):
        oos_m = blended_metrics(oos["weights"])
        lines.append(_row(f"**OOS 채택({oos['folds']}folds)**", oos["weights"], oos_m))
        lines += ["", f"- OOS 평균 Calmar(테스트 창): {oos['oos_metric_mean']:.3f}",
                  "- 채택 근거는 OOS 비중(인샘플은 과적합 가능, 탐색용)."]
    (out_dir / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[mix] done → {out_dir}", flush=True)


if __name__ == "__main__":
    main()
