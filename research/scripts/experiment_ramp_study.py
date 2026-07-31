"""분할 매수/매도 대규모 실험 — 롤링 진입/청산 × 분할 개월 × 시장 국면.

곡선 근사: 슬리브 전체기간 백테스트 곡선(1회) + 현금(flat 0%)을 스케줄 합성
(blend_curves_schedule)해 "매월 1/N 진입(= k/N 보유)"·"마지막 M개월 1/M 청산"
시나리오를 대량 생성한다. 엔진 ramp_in_months 실측과의 오차는 --validate로
정량화(동일 시맨틱의 곡선 근사 — 정수 수량·리밸런스일 차이만 남음).

Usage:
  python research/scripts/experiment_ramp_study.py            # 본 실험(곡선 스윕)
  python research/scripts/experiment_ramp_study.py --validate # 엔진 vs 곡선 오차
Output: research/reports/matrix/ramp_study_<ts>/results.csv + summary.md
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.batch.daily_analysis import load_strategy  # noqa: E402
from research.backtest.engine import research_db_path, run_backtest  # noqa: E402
from research.backtest.metrics import compute_metrics  # noqa: E402
from research.backtest.portfolio import (  # noqa: E402
    _usdkrw_index,
    apply_krw_view,
    blend_curves,
    blend_curves_schedule,
    normalize_curve,
)
from research.backtest.tax_kr import default_tax_model_for_universe  # noqa: E402

START, END = date(2016, 7, 1), date(2026, 7, 1)
SAFE_CODE = "153130"

SLEEVES = [
    ("KR주식", "qlab_alpha_v2"),
    ("KR_ETF", "etf_rotation_kr"),
    ("US주식", "us_value"),
    ("US_ETF", "etf_rotation_us"),
]
RAMPS = [1, 2, 3, 4, 6, 9, 12]  # 1 = 올인
HORIZONS = {"1Y": 12, "3Y": 36}
EXIT_TAPERS = [0, 3, 6]  # 마지막 M개월 분할 청산 (0=일괄)
EXIT_HORIZON = 36


def _add_months(day: date, months: int) -> date:
    y, m = divmod(day.year * 12 + (day.month - 1) + months, 12)
    return date(y, m + 1, 1)


def _cash_like(curve: pd.Series) -> pd.Series:
    return pd.Series(1.0, index=curve.index)


def _dd_bucket(dd: float) -> str:
    if dd > -0.05:
        return "고점권(-5%내)"
    if dd > -0.15:
        return "조정(-5~15%)"
    return "급락(15%+)"


def _metrics(points: list) -> tuple[float, float]:
    """(연환산 CAGR, MDD) — 포인트가 짧으면 (nan, nan)."""
    if len(points) < 40:
        return float("nan"), float("nan")
    m = compute_metrics(points, [])
    return m.cagr, m.mdd


def build_curves() -> dict[str, pd.Series]:
    fx = _usdkrw_index(None)
    curves: dict[str, pd.Series] = {}
    for label, name in SLEEVES:
        strat = load_strategy(name).model_copy(
            update={"start_date": START, "end_date": END}
        )
        res = run_backtest(
            strat, tax_model=default_tax_model_for_universe(strat.universe)
        )
        curves[label] = apply_krw_view(
            normalize_curve(res.equity_curve), strat.universe, fx
        )
        print(f"[ramp] curve ready: {label}", flush=True)

    # DC 68/32 합성 (세전=과세이연)
    dc_strat = load_strategy("dc_risk_rotation_kr").model_copy(
        update={"start_date": START, "end_date": END}
    )
    dc_curve = normalize_curve(run_backtest(dc_strat, tax_model=None).equity_curve)
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            "SELECT date, close FROM prices_daily WHERE stock_code = ?"
            " AND date >= ? AND date <= ? ORDER BY date",
            (SAFE_CODE, START.isoformat(), END.isoformat()),
        ).fetchall()
    safe = normalize_curve([(date.fromisoformat(r[0]), float(r[1])) for r in rows])
    dc_pts = blend_curves([dc_curve, safe], [0.68, 0.32], rebalance="MONTHLY",
                          base_nav=1.0)
    curves["DC_68_32"] = pd.Series(
        [v for _, v in dc_pts], index=pd.to_datetime([d for d, _ in dc_pts])
    )
    print("[ramp] curve ready: DC_68_32", flush=True)
    return curves


def entry_sweep(curves: dict[str, pd.Series], out_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for label, curve in curves.items():
        cash = _cash_like(curve)
        drawdown = curve / curve.cummax() - 1.0
        ret6m = curve.pct_change(126)  # ~6개월 거래일
        first = curve.index[0].date()
        entry = _add_months(date(first.year, first.month, 1), 1)
        while True:
            last_needed = _add_months(entry, max(HORIZONS.values()))
            if pd.Timestamp(last_needed) > curve.index[-1]:
                break
            entry_ts = curve.index[curve.index >= pd.Timestamp(entry)]
            if len(entry_ts) == 0:
                break
            at_entry = entry_ts[0]
            dd = float(drawdown.loc[at_entry])
            mom = ret6m.loc[at_entry]
            mom_sign = "6M+" if (pd.notna(mom) and mom >= 0) else "6M-"
            for n in RAMPS:
                schedule = [
                    (_add_months(entry, j), [min(1.0, (j + 1) / n), 1 - min(1.0, (j + 1) / n)])
                    for j in range(n)
                ]
                pts = blend_curves_schedule(
                    [curve, cash], schedule, base_nav=1.0
                )
                for hlabel, months in HORIZONS.items():
                    h_end = pd.Timestamp(_add_months(entry, months))
                    sub = [(d, v) for d, v in pts if pd.Timestamp(d) < h_end]
                    cagr, mdd = _metrics(sub)
                    rows.append({
                        "study": "entry", "sleeve": label,
                        "entry": entry.isoformat(), "ramp": n,
                        "horizon": hlabel, "cagr": round(cagr, 4),
                        "mdd": round(mdd, 4), "dd_bucket": _dd_bucket(dd),
                        "mom": mom_sign,
                    })
            entry = _add_months(entry, 1)
        print(f"[ramp] entry sweep done: {label}", flush=True)
    return rows


def exit_sweep(curves: dict[str, pd.Series], out_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for label, curve in curves.items():
        cash = _cash_like(curve)
        drawdown = curve / curve.cummax() - 1.0
        first = curve.index[0].date()
        start = _add_months(date(first.year, first.month, 1), 1)
        while True:
            end = _add_months(start, EXIT_HORIZON)
            if pd.Timestamp(end) > curve.index[-1]:
                break
            for m in EXIT_TAPERS:
                if m == 0:
                    schedule = [(start, [1.0, 0.0])]
                else:
                    schedule = [(start, [1.0, 0.0])] + [
                        (_add_months(end, -m + j), [(m - j) / m, j / m])
                        for j in range(1, m + 1)
                    ]
                pts = blend_curves_schedule([curve, cash], schedule, base_nav=1.0)
                sub = [(d, v) for d, v in pts if pd.Timestamp(d) < pd.Timestamp(end)]
                if len(sub) < 200:
                    continue
                terminal = sub[-1][1]
                # 의사결정 시점(taper 시작 = end-M) 낙폭 버킷
                decision = pd.Timestamp(_add_months(end, -max(m, 1)))
                dts = curve.index[curve.index >= decision]
                dd = float(drawdown.loc[dts[0]]) if len(dts) else float("nan")
                rows.append({
                    "study": "exit", "sleeve": label, "entry": start.isoformat(),
                    "ramp": m, "horizon": "3Y",
                    "cagr": round(terminal ** (1 / 3) - 1, 4),
                    "mdd": round(terminal, 4),  # exit study: mdd 칸에 종료NAV 저장
                    "dd_bucket": _dd_bucket(dd), "mom": "-",
                })
            start = _add_months(start, 1)
        print(f"[ramp] exit sweep done: {label}", flush=True)
    return rows


def summarize(rows: list[dict], out_dir: Path) -> None:
    df = pd.DataFrame(rows)
    lines = ["# 분할 매수/매도 롤링 실험 (곡선 근사)", "",
             f"- 곡선: {', '.join(sorted(df['sleeve'].unique()))} · 진입 롤링 월 단위",
             "- 현금 수익 0% 가정(보수적). 값은 올인(ramp=1/일괄 M=0) 대비 Δ 중심.", ""]

    ent = df[df.study == "entry"]
    for hlabel in HORIZONS:
        lines.append(f"## 분할 매수 — 호라이즌 {hlabel}")
        sub = ent[ent.horizon == hlabel]
        base = sub[sub.ramp == 1].set_index(["sleeve", "entry"])
        for sleeve in sorted(sub.sleeve.unique()):
            lines.append(f"### {sleeve}")
            lines.append("| 진입 국면 | N | ΔCAGR 중앙값 | ΔCAGR 최악개선 | ΔMDD 중앙값 | 승률(CAGR) | 표본 |")
            lines.append("|---|---|---|---|---|---|---|")
            s = sub[sub.sleeve == sleeve]
            for bucket in ["고점권(-5%내)", "조정(-5~15%)", "급락(15%+)"]:
                b = s[s.dd_bucket == bucket]
                if b.empty:
                    continue
                for n in [3, 6, 12]:
                    r = b[b.ramp == n].set_index("entry")
                    l = b[b.ramp == 1].set_index("entry")
                    joined = r.join(l, rsuffix="_lump")
                    if joined.empty:
                        continue
                    dc = joined.cagr - joined.cagr_lump
                    dm = joined.mdd - joined.mdd_lump
                    worst_gain = (joined.cagr.min() - joined.cagr_lump.min())
                    lines.append(
                        f"| {bucket} | {n}개월 | {dc.median():+.3f} |"
                        f" {worst_gain:+.3f} | {dm.median():+.3f} |"
                        f" {(dc > 0).mean():.0%} | {len(joined)} |"
                    )
            lines.append("")

    lines.append("## 분할 매도 — 3Y 보유 후 청산 (mdd 칸=종료NAV)")
    ext = df[df.study == "exit"]
    for sleeve in sorted(ext.sleeve.unique()):
        lines.append(f"### {sleeve}")
        lines.append("| 결정시점 국면 | M | Δ종료NAV 중앙값 | 승률 | 표본 |")
        lines.append("|---|---|---|---|---|")
        s = ext[ext.sleeve == sleeve]
        # 조인은 버킷 무관 전체 (sleeve, entry) 기준 — 버킷은 taper 행의
        # 의사결정 시점 국면으로만 분류(일괄 행과 버킷이 달라도 비교 유지).
        lump = s[s.ramp == 0].set_index("entry")["mdd"]
        for m in [3, 6]:
            t = s[s.ramp == m].copy()
            t["lump"] = t["entry"].map(lump)
            t = t.dropna(subset=["lump"])
            t["d"] = t["mdd"] - t["lump"]
            for bucket in ["고점권(-5%내)", "조정(-5~15%)", "급락(15%+)"]:
                g = t[t.dd_bucket == bucket]
                if g.empty:
                    continue
                lines.append(
                    f"| {bucket} | {m}개월 | {g.d.median():+.4f} |"
                    f" {(g.d > 0).mean():.0%} | {len(g)} |"
                )
        w0, w3, w6 = (s[s.ramp == n].mdd.min() for n in (0, 3, 6))
        lines.append(
            f"| (보험) 최악 종료NAV | 일괄/3/6 | {w0:.3f} / {w3:.3f} / {w6:.3f} | | |"
        )
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def validate() -> None:
    """엔진 ramp_in_months 실측 vs 곡선 근사 오차 (etf_rotation_kr, 2Y)."""
    fx = _usdkrw_index(None)
    strat_full = load_strategy("etf_rotation_kr").model_copy(
        update={"start_date": START, "end_date": END})
    full = apply_krw_view(
        normalize_curve(
            run_backtest(strat_full, tax_model=default_tax_model_for_universe(
                strat_full.universe)).equity_curve),
        strat_full.universe, fx)
    cash = _cash_like(full)
    print("[validate] entry ramp engine vs curve (CAGR/MDD)", flush=True)
    for entry in (date(2018, 1, 1), date(2020, 3, 1), date(2022, 7, 1)):
        for n in (3, 6):
            end = _add_months(entry, 24)
            strat = load_strategy("etf_rotation_kr").model_copy(update={
                "start_date": entry, "end_date": end, "ramp_in_months": n})
            res = run_backtest(
                strat,
                tax_model=default_tax_model_for_universe(strat.universe),
            )
            e_cagr, e_mdd = res.metrics.cagr, res.metrics.mdd
            schedule = [
                (_add_months(entry, j),
                 [min(1.0, (j + 1) / n), 1 - min(1.0, (j + 1) / n)])
                for j in range(n)
            ]
            pts = blend_curves_schedule([full, cash], schedule, base_nav=1.0)
            sub = [(d, v) for d, v in pts if pd.Timestamp(d) < pd.Timestamp(end)]
            c_cagr, c_mdd = _metrics(sub)
            print(f"  {entry} N={n}: engine cagr={e_cagr:+.4f} mdd={e_mdd:+.4f}"
                  f" | curve cagr={c_cagr:+.4f} mdd={c_mdd:+.4f}"
                  f" | Δcagr={c_cagr - e_cagr:+.4f}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        validate()
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "research" / "reports" / "matrix" / f"ramp_study_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    curves = build_curves()
    rows = entry_sweep(curves, out_dir) + exit_sweep(curves, out_dir)
    with open(out_dir / "results.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summarize(rows, out_dir)
    print(f"[ramp] done → {out_dir} (cells={len(rows)})", flush=True)


if __name__ == "__main__":
    main()
