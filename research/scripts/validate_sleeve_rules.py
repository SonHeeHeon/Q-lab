"""슬리브별 긴급 매매조건(중간매매 규칙) 검증 — baseline 대비 A/B.

validate_rules.py(KR qlab 전용)의 일반화: 4슬리브 채택 방정식(private 우선
로드)에 stop_loss/take_profit/band_trim 변형을 붙여 3Y/5Y/FULL을 **세후**로
돌리고 Sharpe/MDD/Calmar 변화를 표로 남긴다.

채택 기준(기존 validate_rules와 동일): Sharpe 개선, 또는 MDD 개선하면서
Sharpe 유지(-0.02 이내). 결과는 각 private yaml에 수동 반영한다.

Usage: python research/scripts/validate_sleeve_rules.py [--quick]
Output: research/reports/matrix/sleeve_rules_<ts>/results.csv + summary.md
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
from research.backtest.tax_kr import default_tax_model_for_universe  # noqa: E402

DATA_FLOOR = date(2016, 7, 1)
END = date(2026, 7, 1)
PERIODS: dict[str, int | None] = {"3Y": 1095, "5Y": 1825, "FULL": None}

# 슬리브 → (전략 이름, 룰 변형 목록). 변형 = (이름, StrategyDefinition 오버라이드).
# KR 주식(qlab_alpha_v2)은 기검증 완료(band_trim 1.4 채택, stop/take 기각)라 제외.
SLEEVES: dict[str, tuple[str, list[tuple[str, dict]]]] = {
    "kr_etf": (
        "etf_rotation_kr",
        [
            ("baseline", {}),
            ("stop_loss_10", {"stop_loss_pct": -0.10}),
            ("stop_loss_15", {"stop_loss_pct": -0.15}),
        ],
    ),
    "us_stock_value": (
        "us_value",
        [
            ("baseline", {}),
            ("stop_loss_15", {"stop_loss_pct": -0.15}),
            ("stop_loss_20", {"stop_loss_pct": -0.20}),
            ("take_profit_40", {"take_profit_pct": 0.40}),
            ("band_trim_14", {"band_trim_threshold": 1.4}),
        ],
    ),
    "us_stock_momentum": (
        "us_momentum",
        [
            ("baseline", {}),
            ("stop_loss_15", {"stop_loss_pct": -0.15}),
            ("stop_loss_20", {"stop_loss_pct": -0.20}),
        ],
    ),
    "us_etf": (
        "etf_rotation_us",
        [
            ("baseline", {}),
            ("stop_loss_10", {"stop_loss_pct": -0.10}),
            ("stop_loss_15", {"stop_loss_pct": -0.15}),
        ],
    ),
}


def _period_start(days: int | None) -> date:
    if days is None:
        return DATA_FLOOR
    return max(DATA_FLOOR, END - timedelta(days=days))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="3Y만, ETF 슬리브만")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "research" / "reports" / "matrix" / f"sleeve_rules_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "results.csv"

    sleeves = (
        {k: v for k, v in SLEEVES.items() if k in {"kr_etf", "us_etf"}}
        if args.quick
        else SLEEVES
    )
    periods = {"3Y": PERIODS["3Y"]} if args.quick else PERIODS

    fields = [
        "sleeve", "variant", "period", "cagr", "mdd", "sharpe", "calmar",
        "n_trades", "total_tax",
    ]
    rows: list[dict] = []
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for sleeve, (strategy_name, variants) in sleeves.items():
            base = load_strategy(strategy_name)
            for vname, overrides in variants:
                for plabel, days in periods.items():
                    strat = base.model_copy(
                        update={
                            "start_date": _period_start(days),
                            "end_date": END,
                            **overrides,
                        }
                    )
                    try:
                        res = run_backtest(
                            strat,
                            tax_model=default_tax_model_for_universe(strat.universe),
                        )
                        m = res.metrics
                        row = {
                            "sleeve": sleeve, "variant": vname, "period": plabel,
                            "cagr": round(m.cagr, 4), "mdd": round(m.mdd, 4),
                            "sharpe": round(m.sharpe, 3),
                            "calmar": round(m.cagr / abs(m.mdd), 3) if m.mdd else 0.0,
                            "n_trades": m.n_trades,
                            "total_tax": round(m.total_tax_paid, 0),
                        }
                    except Exception as exc:  # noqa: BLE001 — 한 셀 실패가 스윕을 못 죽이게
                        row = {"sleeve": sleeve, "variant": vname, "period": plabel,
                               "cagr": 0, "mdd": 0, "sharpe": 0, "calmar": 0,
                               "n_trades": 0, "total_tax": 0}
                        print(f"[rules:warn] {sleeve}/{vname}/{plabel}: {exc}", flush=True)
                    writer.writerow(row)
                    fh.flush()
                    rows.append(row)
                    print(f"[rules] {sleeve}/{vname}/{plabel}: sharpe={row['sharpe']}"
                          f" mdd={row['mdd']} calmar={row['calmar']}", flush=True)

    _write_summary(out_dir, rows)
    print(f"[rules] done → {out_dir}", flush=True)


def _write_summary(out_dir: Path, rows: list[dict]) -> None:
    lines = ["# 슬리브 긴급조건 A/B (세후)", "",
             "채택 기준: Sharpe 개선, 또는 MDD 개선하면서 Sharpe 유지(-0.02 이내).", ""]
    sleeves = sorted({r["sleeve"] for r in rows})
    for sleeve in sleeves:
        lines.append(f"## {sleeve}")
        lines.append("| variant | period | Sharpe | MDD | Calmar | ΔSharpe | ΔMDD |")
        lines.append("|---|---|---|---|---|---|---|")
        base = {r["period"]: r for r in rows
                if r["sleeve"] == sleeve and r["variant"] == "baseline"}
        for r in [x for x in rows if x["sleeve"] == sleeve]:
            b = base.get(r["period"], {})
            ds = round(r["sharpe"] - b.get("sharpe", 0), 3)
            dm = round(r["mdd"] - b.get("mdd", 0), 4)
            lines.append(
                f"| {r['variant']} | {r['period']} | {r['sharpe']} | {r['mdd']} |"
                f" {r['calmar']} | {ds:+} | {dm:+} |"
            )
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
