"""계좌별 전용 A/B — ISA 슬리브 구성 · 연금저축 로테이션 · IRP(=DC) 재확인.

- ISA: KR주식(qlab)+KR ETF 로테이션 비중 4구성(100/0, 70/30, 50/50, 0/100)을
  **ISA 세금모델**(과세 ETF 손익통산+한도 초과 9.9%)로 비교. KR 주식 매매차익은
  어차피 비과세라 ISA 이점은 과세 ETF 슬리브에서만 발생 — 우승 구성에 대해
  일반계좌 세금(per-sell 15.4%) 대비 델타도 산출한다.
- 연금저축: dc_risk_rotation_kr 변형(top_n×게이트) 100% 단독, 세전(과세이연).
- IRP: DC 채택 구성(top3 nogate 68% + 단기채 보유 32%) 수치 재확인(동일 규정).

Usage: python research/scripts/experiment_accounts.py [--quick]
Output: research/reports/matrix/accounts_<ts>/results.csv + summary.md
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.batch.daily_analysis import load_strategy  # noqa: E402
from research.backtest.engine import research_db_path, run_backtest  # noqa: E402
from research.backtest.metrics import compute_metrics  # noqa: E402
from research.backtest.portfolio import blend_curves, normalize_curve  # noqa: E402
from research.backtest.tax_kr import ISATaxModel, TaxModel  # noqa: E402

DATA_FLOOR = date(2016, 7, 1)
END = date(2026, 7, 1)
PERIODS: dict[str, int | None] = {"3Y": 1095, "5Y": 1825, "FULL": None}
SAFE_CODE = "153130"

ISA_MIXES = [("qlab100", 1.0), ("qlab70_etf30", 0.7),
             ("qlab50_etf50", 0.5), ("etf100", 0.0)]
PENSION_VARIANTS = [
    ("top3_nogate", {}),
    ("top2_nogate", {"top_n": 2}),
    ("top4_nogate", {"top_n": 4}),
    ("top3_gate", {"abs_momentum_gate": True}),
]


def _period_start(days: int | None) -> date:
    return DATA_FLOOR if days is None else max(DATA_FLOOR, END - timedelta(days=days))


def _m(pts) -> dict:
    m = compute_metrics(pts, [])
    return {"cagr": round(m.cagr, 4), "mdd": round(m.mdd, 4),
            "sharpe": round(m.sharpe, 3),
            "calmar": round(m.cagr / abs(m.mdd), 3) if m.mdd else 0.0}


def _slice(curve, start: date):
    sliced = curve[curve.index >= str(start)]
    if sliced.empty:
        return sliced
    return sliced / float(sliced.iloc[0])


def _buyhold_curve(code: str):
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            "SELECT date, close FROM prices_daily WHERE stock_code = ?"
            " AND date >= ? AND date <= ? ORDER BY date",
            (code, DATA_FLOOR.isoformat(), END.isoformat()),
        ).fetchall()
    return normalize_curve([(date.fromisoformat(r[0]), float(r[1])) for r in rows])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="3Y만")
    args = parser.parse_args()
    periods = {"3Y": PERIODS["3Y"]} if args.quick else PERIODS

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "research" / "reports" / "matrix" / f"accounts_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    def add(account: str, variant: str, plabel: str, pts) -> None:
        row = {"account": account, "variant": variant, "period": plabel, **_m(pts)}
        rows.append(row)
        print(f"[acct] {account}/{variant}/{plabel}: {row}", flush=True)

    # --- 곡선 캐시 (FULL 1회 실행 후 기간 슬라이스) --------------------------
    def curve_of(name: str, tax_model) -> "object":
        strat = load_strategy(name).model_copy(
            update={"start_date": DATA_FLOOR, "end_date": END})
        return normalize_curve(
            run_backtest(strat, tax_model=tax_model).equity_curve)

    print("[acct] building curves…", flush=True)
    qlab = curve_of("qlab_alpha_v2", None)  # 주식만 보유 — ISA/일반 동일(비과세)
    etf_isa = curve_of("etf_rotation_kr", ISATaxModel())
    etf_general = curve_of("etf_rotation_kr", TaxModel())

    # --- ISA: 구성 비교 (ISA 세금모델) --------------------------------------
    for vname, w in ISA_MIXES:
        for plabel, days in periods.items():
            start = _period_start(days)
            q, e = _slice(qlab, start), _slice(etf_isa, start)
            if w == 1.0:
                pts = [(i.date(), float(v)) for i, v in q.items()]
            elif w == 0.0:
                pts = [(i.date(), float(v)) for i, v in e.items()]
            else:
                pts = blend_curves([q, e], [w, 1 - w], rebalance="MONTHLY")
            add("isa", vname, plabel, pts)

    # 일반계좌 세금으로 같은 구성(70/30) — ISA 이점 델타 확인용
    for plabel, days in periods.items():
        start = _period_start(days)
        pts = blend_curves(
            [_slice(qlab, start), _slice(etf_general, start)],
            [0.7, 0.3], rebalance="MONTHLY",
        )
        add("isa_ref_general", "qlab70_etf30_일반과세", plabel, pts)

    # --- 연금저축: dc_risk 변형 100% (세전=과세이연) -------------------------
    base = load_strategy("dc_risk_rotation_kr")
    for vname, overrides in PENSION_VARIANTS:
        for plabel, days in periods.items():
            strat = base.model_copy(update={
                "start_date": _period_start(days), "end_date": END, **overrides})
            try:
                res = run_backtest(strat, tax_model=None)
                pts = [(p.date, p.nav) for p in res.equity_curve]
                add("pension", vname, plabel, pts)
            except Exception as exc:  # noqa: BLE001
                print(f"[acct:warn] pension/{vname}/{plabel}: {exc}", flush=True)

    # --- IRP: DC 채택 구성 재확인 (top3 nogate 68 + 단기채 32) ---------------
    dc_risk = curve_of("dc_risk_rotation_kr", None)
    safe = _buyhold_curve(SAFE_CODE)
    for plabel, days in periods.items():
        start = _period_start(days)
        pts = blend_curves(
            [_slice(dc_risk, start), _slice(safe, start)],
            [0.68, 0.32], rebalance="MONTHLY",
        )
        add("irp", "dc_adopted_68_32", plabel, pts)

    # --- 저장 ---------------------------------------------------------------
    fields = ["account", "variant", "period", "cagr", "mdd", "sharpe", "calmar"]
    with open(out_dir / "results.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    lines = ["# 계좌별 전용 A/B (ISA=ISA세금·연금저축=세전·IRP=DC 재확인)", ""]
    for account in ("isa", "isa_ref_general", "pension", "irp"):
        subset = [r for r in rows if r["account"] == account]
        if not subset:
            continue
        lines += [f"## {account}",
                  "| variant | period | CAGR | MDD | Sharpe | Calmar |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| {r['variant']} | {r['period']} | {r['cagr']} | {r['mdd']} |"
                  f" {r['sharpe']} | {r['calmar']} |" for r in subset]
        lines.append("")
    lines += ["- ISA 세금모델은 과세 ETF 손익통산+한도(200만) 초과 9.9% —"
              " 배당·이자 통산은 데이터 없음(가격수익 기준)이라 미반영.",
              "- 연금저축은 과세이연이라 세전 수치가 정확."]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[acct] done → {out_dir}", flush=True)


if __name__ == "__main__":
    main()
