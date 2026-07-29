"""DC 퇴직연금 70/32 이중 로테이션 A/B — 세전(과세이연).

위험 슬리브: top_n{2,3} × 게이트{off,on} + 게이트판 stop_loss 변형.
안전 슬리브: top_n{1,2}. 기간 3Y/5Y/FULL. 마지막에 채택 설정 68/32 합성.
채택 기준(기존과 동일): Sharpe 개선, 또는 MDD 개선하면서 Sharpe 유지(-0.02 이내).

Usage: python research/scripts/experiment_dc.py [--quick]
Output: research/reports/matrix/dc_experiment_<ts>/results.csv + summary.md
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
from research.backtest.engine import (  # noqa: E402
    get_universe,
    research_db_path,
    run_backtest,
)
from research.backtest.metrics import compute_metrics  # noqa: E402
from research.backtest.portfolio import blend_curves, normalize_curve  # noqa: E402
import sqlite3  # noqa: E402

DATA_FLOOR = date(2016, 7, 1)
END = date(2026, 7, 1)
PERIODS: dict[str, int | None] = {"3Y": 1095, "5Y": 1825, "FULL": None}
RISK_TARGET = 0.68  # 규제 70% - 드리프트 버퍼 2%p

VARIANTS: dict[str, tuple[str, list[tuple[str, dict]]]] = {
    "dc_risk": (
        "dc_risk_rotation_kr",
        [
            ("top3_nogate", {}),
            ("top2_nogate", {"top_n": 2}),
            ("top3_gate", {"abs_momentum_gate": True}),
            ("top2_gate", {"top_n": 2, "abs_momentum_gate": True}),
            ("top3_gate_sl15", {"abs_momentum_gate": True, "stop_loss_pct": -0.15}),
        ],
    ),
    "dc_safe": (
        "dc_safe_rotation_kr",
        [("top2", {}), ("top1", {"top_n": 1})],
    ),
}


# 안전 슬리브 단순보유 벤치마크 — 로테이션이 비용·휩쏘로 열위일 가능성 검증용.
SAFE_HOLD_CODES = ["153130", "114260", "148070"]


def _period_start(days: int | None) -> date:
    return DATA_FLOOR if days is None else max(DATA_FLOOR, END - timedelta(days=days))


def _buyhold_points(code: str, start: date) -> list[tuple[date, float]]:
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            "SELECT date, close FROM prices_daily WHERE stock_code = ?"
            " AND date >= ? AND date <= ? ORDER BY date",
            (code, start.isoformat(), END.isoformat()),
        ).fetchall()
    return [(date.fromisoformat(r[0]), float(r[1])) for r in rows]


def _points_metrics(pts: list[tuple[date, float]]) -> dict:
    m = compute_metrics(pts, [])
    return {
        "cagr": round(m.cagr, 4), "mdd": round(m.mdd, 4),
        "sharpe": round(m.sharpe, 3),
        "calmar": round(m.cagr / abs(m.mdd), 3) if m.mdd else 0.0,
        "n_trades": 0,
    }


def _metrics_row(res) -> dict:
    m = res.metrics
    return {
        "cagr": round(m.cagr, 4), "mdd": round(m.mdd, 4),
        "sharpe": round(m.sharpe, 3),
        "calmar": round(m.cagr / abs(m.mdd), 3) if m.mdd else 0.0,
        "n_trades": m.n_trades,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="3Y만")
    parser.add_argument("--risk-variant", default=None,
                        help="합성에 쓸 위험 변형(기본: FULL Sharpe 최고)")
    parser.add_argument("--safe-variant", default=None)
    parser.add_argument("--safe-hold", default=None, metavar="CODE",
                        help="안전 레그를 로테이션 대신 지정 코드 단순보유로 합성")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "research" / "reports" / "matrix" / f"dc_experiment_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    periods = {"3Y": PERIODS["3Y"]} if args.quick else PERIODS

    fields = ["sleeve", "variant", "period", "cagr", "mdd", "sharpe", "calmar", "n_trades"]
    rows: list[dict] = []
    best_result: dict[tuple[str, str], object] = {}  # (sleeve, variant) -> 최장기간 RunResult
    with open(out_dir / "results.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for sleeve, (name, variants) in VARIANTS.items():
            base = load_strategy(name)
            for vname, overrides in variants:
                for plabel, days in periods.items():
                    strat = base.model_copy(update={
                        "start_date": _period_start(days), "end_date": END, **overrides,
                    })
                    try:
                        res = run_backtest(strat, tax_model=None)  # DC=과세이연
                        row = {"sleeve": sleeve, "variant": vname, "period": plabel,
                               **_metrics_row(res)}
                        if plabel == ("3Y" if args.quick else "FULL"):
                            best_result[(sleeve, vname)] = res
                    except Exception as exc:  # noqa: BLE001 — 한 셀 실패 격리
                        row = {"sleeve": sleeve, "variant": vname, "period": plabel,
                               "cagr": 0, "mdd": 0, "sharpe": 0, "calmar": 0, "n_trades": 0}
                        print(f"[dc:warn] {sleeve}/{vname}/{plabel}: {exc}", flush=True)
                    writer.writerow(row); fh.flush(); rows.append(row)
                    print(f"[dc] {sleeve}/{vname}/{plabel}: {row}", flush=True)

    # 안전 단순보유 벤치마크 행(비교용 — 로테이션 대비 우열 판단 근거)
    for code in SAFE_HOLD_CODES:
        for plabel, days in periods.items():
            pts = _buyhold_points(code, _period_start(days))
            if not pts:
                continue
            row = {"sleeve": "dc_safe_hold", "variant": f"hold_{code}",
                   "period": plabel, **_points_metrics(pts)}
            rows.append(row)
            print(f"[dc] dc_safe_hold/{code}/{plabel}: {row}", flush=True)

    # 68/32 합성: 변형 지정 없으면 FULL(또는 quick=3Y) Sharpe 최고 변형 자동 선택
    # (채택 기준의 1순위가 Sharpe라 Sharpe로 고른다. 동률은 Calmar.)
    def _pick(sleeve: str, forced: str | None) -> str:
        if forced:
            return forced
        plabel = "3Y" if args.quick else "FULL"
        cands = [r for r in rows if r["sleeve"] == sleeve and r["period"] == plabel]
        return max(cands, key=lambda r: (r["sharpe"], r["calmar"]))["variant"]

    risk_pick = _pick("dc_risk", args.risk_variant)
    if args.safe_hold:
        safe_pick = f"hold_{args.safe_hold}"
        safe_curve = normalize_curve(
            _buyhold_points(args.safe_hold, _period_start(periods[list(periods)[-1]]))
        )
    else:
        safe_pick = _pick("dc_safe", args.safe_variant)
        safe_curve = normalize_curve(best_result[("dc_safe", safe_pick)].equity_curve)
    curves = [normalize_curve(best_result[("dc_risk", risk_pick)].equity_curve),
              safe_curve]
    pts = blend_curves(curves, [RISK_TARGET, 1 - RISK_TARGET], rebalance="MONTHLY")
    m = compute_metrics(pts, [])
    blend_row = {"risk": risk_pick, "safe": safe_pick,
                 "cagr": round(m.cagr, 4), "mdd": round(m.mdd, 4),
                 "sharpe": round(m.sharpe, 3),
                 "calmar": round(m.cagr / abs(m.mdd), 3) if m.mdd else 0.0}
    print(f"[dc] blend 68/32 ({risk_pick}+{safe_pick}): {blend_row}", flush=True)

    # 유니버스 커버리지(연도별 종목 수) — 정직 노트용
    coverage = []
    for year in range(DATA_FLOOR.year, END.year + 1):
        day = date(year, 7, 1)
        if day > END:
            break
        coverage.append({
            "year": year,
            "risk_n": len(get_universe("ETF_KR_DC_RISK", as_of=day)),
            "safe_n": len(get_universe("ETF_KR_DC_SAFE", as_of=day)),
        })

    _write_summary(out_dir, rows, blend_row, coverage)
    print(f"[dc] done → {out_dir}", flush=True)


def _write_summary(out_dir: Path, rows: list[dict], blend_row: dict,
                   coverage: list[dict]) -> None:
    lines = ["# DC 퇴직연금 A/B (세전=과세이연)", "",
             "채택 기준: Sharpe 개선, 또는 MDD 개선하면서 Sharpe 유지(-0.02 이내).", ""]
    for sleeve in ("dc_risk", "dc_safe", "dc_safe_hold"):
        lines += [f"## {sleeve}",
                  "| variant | period | CAGR | MDD | Sharpe | Calmar |", "|---|---|---|---|---|---|"]
        for r in [x for x in rows if x["sleeve"] == sleeve]:
            lines.append(f"| {r['variant']} | {r['period']} | {r['cagr']} | {r['mdd']} |"
                         f" {r['sharpe']} | {r['calmar']} |")
        lines.append("")
    lines += ["## 68/32 합성 (월간 리셋)",
              f"- 구성: 위험 {blend_row['risk']} 68% + 안전 {blend_row['safe']} 32%",
              f"- CAGR {blend_row['cagr']} · MDD {blend_row['mdd']} ·"
              f" Sharpe {blend_row['sharpe']} · Calmar {blend_row['calmar']}", "",
              "## 유니버스 커버리지(7/1 기준)",
              "| year | risk_n | safe_n |", "|---|---|---|"]
    lines += [f"| {c['year']} | {c['risk_n']} | {c['safe_n']} |" for c in coverage]
    lines += ["", "- 68(≠70) = 리밸런스 간 드리프트 버퍼 2%p."
              " 실계좌는 KIS 퇴직연금 시스템이 70% 초과 주문을 추가 차단(이중 방어)."]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
