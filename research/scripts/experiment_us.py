"""US quant factor A/B experiment — single-factor IC screening + multi-factor
composition backtests across 1/2/3/5/7/10/15-year periods, ranked by Calmar.

Two universes: US_LARGE (stocks, SEC fundamentals + price factors) and ETF_US
(ETFs, price factors only). Answers "which factor / which combination is best,
per holding horizon" and splits long-term (>=3Y) vs short-term (<3Y) winners.

Stage 1 — IC (Information Coefficient): rank-correlation between a factor today
and the forward 3-month return, averaged over history. Fast single-factor
performance screen (higher_is_better factors are sign-flipped so positive IC =
predictive). Stage 2 — full backtests of curated compositions per period.

Honesty: current-members-only universe → survivorship bias (documented in the
report); backtests are compared to SPY buy-and-hold total return.

Usage:
    python research/scripts/experiment_us.py            # full sweep (~1-1.5h)
    python research/scripts/experiment_us.py --quick    # tiny smoke subset
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sqlite3

from research.backtest.engine import _factor_series, get_universe, run_backtest
from shared.db.session import research_db_path
from shared.domain.strategy import FactorGroup, GroupFactor, StrategyDefinition

PERIODS = [
    ("1Y", 365), ("2Y", 730), ("3Y", 1095), ("5Y", 1825),
    ("7Y", 2555), ("10Y", 3650), ("15Y", 5475),
]
END = date(2026, 7, 1)

# factor -> higher_is_better (for IC sign + group construction)
STOCK_FACTORS: dict[str, bool] = {
    "PER": False, "PBR": False, "PSR": False,
    "ROE": True, "ROA": True, "OP_MARGIN": True, "GP_A": True,
    "ACCRUALS": False, "ASSET_GROWTH": False,
    "FCF_YIELD": True, "SHAREHOLDER_YIELD": True, "EPS_GROWTH_YOY": True,
    "MOMENTUM_12M": True, "MOMENTUM_6M": True,
    "VOLATILITY_252D": False, "BETA_252D": False,
}


def _g(name: str, weight: float, *factors: str) -> FactorGroup:
    return FactorGroup(
        name=name, weight=weight,
        factors=[GroupFactor(factor=f, higher_is_better=STOCK_FACTORS.get(f, True))
                 for f in factors],
    )


# Curated stock compositions — each a hypothesis about what drives US returns.
STOCK_VARIANTS: dict[str, list[FactorGroup]] = {
    "value": [_g("value", 1.0, "PER", "PBR", "PSR", "FCF_YIELD", "SHAREHOLDER_YIELD")],
    "quality": [_g("quality", 1.0, "ROE", "ROA", "GP_A", "ACCRUALS", "OP_MARGIN")],
    "momentum": [_g("momentum", 1.0, "MOMENTUM_12M", "MOMENTUM_6M")],
    "lowvol": [_g("lowvol", 1.0, "VOLATILITY_252D", "BETA_252D")],
    "qual_value": [_g("quality", 1.0, "ROE", "GP_A", "ACCRUALS"),
                   _g("value", 1.0, "PBR", "FCF_YIELD", "SHAREHOLDER_YIELD")],
    "qual_mom": [_g("quality", 1.0, "ROE", "GP_A", "ACCRUALS"),
                 _g("momentum", 1.0, "MOMENTUM_12M")],
    "multifactor": [_g("quality", 1.0, "ROE", "GP_A", "ACCRUALS"),
                    _g("value", 1.0, "PBR", "FCF_YIELD"),
                    _g("momentum", 1.0, "MOMENTUM_12M"),
                    _g("lowvol", 1.0, "VOLATILITY_252D", "BETA_252D")],
}

# ETFs have no fundamentals — price factors + optional absolute-momentum gate.
ETF_VARIANTS: dict[str, dict] = {
    "etf_mom": {"groups": [_g("momentum", 1.0, "MOMENTUM_12M", "MOMENTUM_6M")]},
    "etf_lowvol": {"groups": [_g("lowvol", 1.0, "VOLATILITY_252D")]},
    "etf_mom_gate": {"groups": [_g("momentum", 1.0, "MOMENTUM_12M")], "gate": True},
    "etf_mom_lowvol": {"groups": [_g("momentum", 1.0, "MOMENTUM_12M"),
                                  _g("lowvol", 1.0, "VOLATILITY_252D")]},
}


def _strategy(name, universe, groups, start, end, *, top_n, gate=False) -> StrategyDefinition:
    return StrategyDefinition(
        name=name, description=f"US experiment {name}", universe=universe,
        rebalance_freq="QUARTERLY", filters=[], top_n=top_n, factors=[], groups=groups,
        start_date=start, end_date=end,
        min_groups=1, abs_momentum_gate=gate, abs_momentum_factor="MOMENTUM_12M",
    )


def _calmar(m) -> float:
    return m.cagr / abs(m.mdd) if m.mdd else 0.0


# ---------------------------------------------------------------- IC screening
def _price_panel(db_path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT ticker, date, COALESCE(adj_close, close) AS close"
            " FROM prices_daily_us ORDER BY date",
            conn,
        )
    return df.pivot_table(index="date", columns="ticker", values="close")


def compute_ic(factor: str, higher: bool, panel: pd.DataFrame,
               eval_dates: list[str], horizon: int, db_path) -> dict:
    """Mean rank-IC of a factor vs forward `horizon`-trading-day returns."""
    idx = list(panel.index)
    pos = {d: i for i, d in enumerate(idx)}
    ics: list[float] = []
    for d in eval_dates:
        if d not in pos or pos[d] + horizon >= len(idx):
            continue
        as_of = date.fromisoformat(d)
        fac = _factor_series(factor, list(panel.columns), as_of=as_of, db_path=db_path, warnings=None)
        if fac.empty:
            continue
        if not higher:
            fac = -fac  # flip so a positive IC always means "predictive"
        fwd_start = panel.iloc[pos[d]]
        fwd_end = panel.iloc[pos[d] + horizon]
        fwd = (fwd_end / fwd_start - 1.0).dropna()
        joined = pd.concat([fac.rename("f"), fwd.rename("r")], axis=1, join="inner").dropna()
        if len(joined) >= 20:
            ic = joined["f"].corr(joined["r"], method="spearman")
            if ic == ic:
                ics.append(float(ic))
    if not ics:
        return {"factor": factor, "n": 0, "mean_ic": 0.0, "ic_ir": 0.0, "hit_rate": 0.0}
    s = pd.Series(ics)
    return {
        "factor": factor, "n": len(ics),
        "mean_ic": round(float(s.mean()), 4),
        "ic_ir": round(float(s.mean() / s.std()), 3) if s.std() else 0.0,
        "hit_rate": round(float((s > 0).mean()), 3),
    }


def run_ic(out_dir: Path, db_path, *, quick: bool) -> None:
    panel = _price_panel(db_path)
    dates = list(panel.index)
    # every ~2 months from 2012 (fundamentals available) to end−horizon
    start_i = next((i for i, d in enumerate(dates) if d >= "2012-01-01"), 0)
    step = 42  # ~2 trading months
    eval_dates = dates[start_i:len(dates) - 70:step]
    factors = list(STOCK_FACTORS)
    if quick:
        eval_dates = eval_dates[::4]
        factors = ["MOMENTUM_12M", "GP_A", "PBR", "VOLATILITY_252D"]
    rows = [compute_ic(f, STOCK_FACTORS[f], panel, eval_dates, 63, db_path) for f in factors]
    rows.sort(key=lambda r: r["mean_ic"], reverse=True)
    _write_csv(out_dir / "ic_table.csv", rows,
               ["factor", "mean_ic", "ic_ir", "hit_rate", "n"])
    print(f"[ic] {len(factors)} factors over {len(eval_dates)} dates -> ic_table.csv")


# ---------------------------------------------------------------- backtests
def _spy_return(start: date, end: date, db_path) -> float:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT COALESCE(adj_close, close) FROM prices_daily_us"
            " WHERE ticker='SPY' AND date BETWEEN ? AND ? ORDER BY date",
            [start.isoformat(), end.isoformat()],
        ).fetchall()
    if len(rows) < 2 or rows[0][0] <= 0:
        return 0.0
    return float(rows[-1][0] / rows[0][0] - 1.0)


def run_backtests(out_dir: Path, db_path, *, quick: bool) -> list[dict]:
    results: list[dict] = []
    csv_path = out_dir / "backtest_results.csv"
    fields = ["universe", "variant", "period", "cagr", "mdd", "sharpe",
              "calmar", "n_trades", "spy_return", "excess_vs_spy"]
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()

        periods = PERIODS[:2] if quick else PERIODS
        jobs = []
        stock_vars = {"multifactor": STOCK_VARIANTS["multifactor"]} if quick else STOCK_VARIANTS
        etf_vars = {"etf_mom": ETF_VARIANTS["etf_mom"]} if quick else ETF_VARIANTS
        for name, groups in stock_vars.items():
            jobs.append(("US_LARGE", name, groups, 25, False))
        for name, cfg in etf_vars.items():
            jobs.append(("ETF_US", name, cfg["groups"], 5, cfg.get("gate", False)))

        for universe, variant, groups, top_n, gate in jobs:
            for label, days in periods:
                start = END - timedelta(days=days)
                try:
                    strat = _strategy(f"{variant}_{label}", universe, groups, start, END,
                                      top_n=top_n, gate=gate)
                    res = run_backtest(strat)
                    m = res.metrics
                    spy = _spy_return(start, END, db_path)
                    total = res.final_nav / res.initial_nav - 1.0
                    row = {
                        "universe": universe, "variant": variant, "period": label,
                        "cagr": round(m.cagr, 4), "mdd": round(m.mdd, 4),
                        "sharpe": round(m.sharpe, 3), "calmar": round(_calmar(m), 3),
                        "n_trades": m.n_trades, "spy_return": round(spy, 4),
                        "excess_vs_spy": round(total - spy, 4),
                    }
                except Exception as exc:  # noqa: BLE001 - one cell failing shouldn't kill the sweep
                    row = {"universe": universe, "variant": variant, "period": label,
                           "cagr": 0, "mdd": 0, "sharpe": 0, "calmar": 0, "n_trades": 0,
                           "spy_return": 0, "excess_vs_spy": 0}
                    print(f"[bt:warn] {universe}/{variant}/{label}: {exc}")
                writer.writerow(row)
                fh.flush()  # incremental — partial results survive a crash
                results.append(row)
                print(f"[bt] {universe}/{variant}/{label}: calmar={row['calmar']} cagr={row['cagr']}")
    return results


def write_summary(out_dir: Path, results: list[dict]) -> None:
    df = pd.DataFrame(results)
    lines = ["# US 퀀트 A/B 실험 결과", ""]
    lines.append("> ⚠️ **생존편향**: 현재 구성종목만 사용 → 장기 성과는 낙관 편향 가능"
                 "(무료 데이터 한계). 벤치마크=SPY 총수익.")
    lines.append("")
    for universe in df["universe"].unique():
        sub = df[df["universe"] == universe]
        lines.append(f"## {universe}")
        # per-period winner by Calmar
        lines.append("\n| 기간 | 우승(Calmar) | Calmar | CAGR | MDD | vs SPY |")
        lines.append("|---|---|---|---|---|---|")
        for label, _ in PERIODS:
            cell = sub[sub["period"] == label]
            if cell.empty:
                continue
            best = cell.loc[cell["calmar"].idxmax()]
            lines.append(f"| {label} | {best['variant']} | {best['calmar']} | "
                         f"{best['cagr']} | {best['mdd']} | {best['excess_vs_spy']:+} |")
        # long (>=3Y) vs short (<3Y) aggregate winner
        short = sub[sub["period"].isin(["1Y", "2Y"])]
        long = sub[sub["period"].isin(["3Y", "5Y", "7Y", "10Y", "15Y"])]
        if not short.empty:
            sw = short.groupby("variant")["calmar"].mean().idxmax()
            lines.append(f"\n- **단기(<3Y) 최적**: `{sw}` (평균 Calmar {short.groupby('variant')['calmar'].mean().max():.3f})")
        if not long.empty:
            lw = long.groupby("variant")["calmar"].mean().idxmax()
            lines.append(f"- **장기(>=3Y) 최적**: `{lw}` (평균 Calmar {long.groupby('variant')['calmar'].mean().max():.3f})")
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("[report] summary.md written")


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="tiny smoke subset")
    ap.add_argument("--skip-ic", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    db_path = str(research_db_path)

    ts = "quick" if args.quick else "full"
    out_dir = args.out or (PROJECT_ROOT / "research" / "reports" / "matrix" / f"us_experiment_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[experiment] out={out_dir}")

    if not args.skip_ic:
        run_ic(out_dir, db_path, quick=args.quick)
    results = run_backtests(out_dir, db_path, quick=args.quick)
    write_summary(out_dir, results)
    print("[experiment] done")


if __name__ == "__main__":
    main()
