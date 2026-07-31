"""롤링 3Y 전략 토너먼트 — "어느 3년을 잘라도 덜 배신하는 방정식" 찾기.

개인 계좌(2029-12 청산, 잔여 ~3.4년) 관점: 슬리브별 후보 전략의 전체기간
곡선(세후·KRW)을 1회씩 만들고, 시작점을 3개월 간격으로 미는 3년 창에서
CAGR/MDD/Calmar 분포·우승 횟수·최악값을 비교한다.

곡선 슬라이스 근사(진입 시점 재시작이 아니라 기존 경로 편승)는 ramp study
검증에서 상대 비교 유효성이 확인됨 — 동일 창에서 후보 간 비교라 공정하다.

Usage: python research/scripts/experiment_rolling3y.py
Output: research/reports/matrix/rolling3y_<ts>/results.csv + summary.md
"""
from __future__ import annotations

import csv
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.batch.daily_analysis import load_strategy  # noqa: E402
from research.backtest.engine import run_backtest  # noqa: E402
from research.backtest.metrics import compute_metrics  # noqa: E402
from research.backtest.portfolio import (  # noqa: E402
    _usdkrw_index,
    apply_krw_view,
    normalize_curve,
)
from research.backtest.tax_kr import default_tax_model_for_universe  # noqa: E402

START, END = date(2016, 7, 1), date(2026, 7, 1)
WINDOW_MONTHS = 36
STEP_MONTHS = 3

# 슬리브 → [(라벨, 전략 이름, 오버라이드)] — private 우선 로더 그대로.
CANDIDATES: dict[str, list[tuple[str, str, dict]]] = {
    "KR주식": [
        ("qlab_alpha_v2(채택)", "qlab_alpha_v2", {}),
        ("value_v1(공개기본)", "value_v1", {}),
    ],
    "KR_ETF": [
        ("게이트+손절(채택)", "etf_rotation_kr", {}),
        ("게이트만", "etf_rotation_kr", {"stop_loss_pct": None,
                                          "abs_momentum_gate": True}),
        ("게이트없음", "etf_rotation_kr", {"stop_loss_pct": None,
                                           "abs_momentum_gate": False}),
    ],
    "US주식": [
        ("us_value(채택)", "us_value", {}),
        ("us_momentum", "us_momentum", {}),
        ("us_multifactor", "us_multifactor", {}),
        ("us_stock_v1(공개기본)", "us_stock_v1", {}),
    ],
    "US_ETF": [
        ("게이트(채택)", "etf_rotation_us", {}),
        ("게이트없음", "etf_rotation_us", {"abs_momentum_gate": False}),
    ],
}


def _add_months(day: date, months: int) -> date:
    y, m = divmod(day.year * 12 + (day.month - 1) + months, 12)
    return date(y, m + 1, 1)


def build_curve(name: str, overrides: dict) -> pd.Series:
    strat = load_strategy(name).model_copy(
        update={"start_date": START, "end_date": END, **overrides}
    )
    res = run_backtest(
        strat, tax_model=default_tax_model_for_universe(strat.universe)
    )
    return apply_krw_view(
        normalize_curve(res.equity_curve), strat.universe, _usdkrw_index(None)
    )


def window_metrics(curve: pd.Series, start: date) -> tuple[float, float] | None:
    end = pd.Timestamp(_add_months(start, WINDOW_MONTHS))
    sub = curve[(curve.index >= pd.Timestamp(start)) & (curve.index < end)]
    if len(sub) < 500:  # 3년 거래일의 ~2/3 미만이면 커버리지 부족
        return None
    sub = sub / float(sub.iloc[0])
    pts = [(i.date(), float(v)) for i, v in sub.items()]
    m = compute_metrics(pts, [])
    return m.cagr, m.mdd


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "research" / "reports" / "matrix" / f"rolling3y_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for sleeve, candidates in CANDIDATES.items():
        curves: dict[str, pd.Series] = {}
        for label, name, overrides in candidates:
            try:
                curves[label] = build_curve(name, overrides)
                print(f"[3y] curve ready: {sleeve}/{label}", flush=True)
            except FileNotFoundError:
                print(f"[3y:warn] {sleeve}/{label}: 전략 파일 없음 — 스킵", flush=True)
        start = START
        while _add_months(start, WINDOW_MONTHS) <= END:
            for label, curve in curves.items():
                metric = window_metrics(curve, start)
                if metric is None:
                    continue
                cagr, mdd = metric
                calmar = cagr / abs(mdd) if mdd else 0.0
                rows.append({
                    "sleeve": sleeve, "candidate": label,
                    "window_start": start.isoformat(),
                    "cagr": round(cagr, 4), "mdd": round(mdd, 4),
                    "calmar": round(calmar, 3),
                })
            start = _add_months(start, STEP_MONTHS)
        print(f"[3y] windows done: {sleeve}", flush=True)

    with open(out_dir / "results.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    df = pd.DataFrame(rows)
    lines = ["# 롤링 3Y 전략 토너먼트 (세후·KRW, 3개월 스텝)", "",
             "- 판정 우선순위: Calmar 우승 횟수 → 최악 CAGR → MDD 중앙값",
             "  (3년 뒤 청산 계좌 = 낙폭·최악 시나리오가 수익만큼 중요)", ""]
    for sleeve in CANDIDATES:
        s = df[df.sleeve == sleeve]
        if s.empty:
            continue
        # 창별 Calmar/CAGR 우승자 집계
        calmar_wins = s.loc[s.groupby("window_start").calmar.idxmax()][
            "candidate"].value_counts()
        cagr_wins = s.loc[s.groupby("window_start").cagr.idxmax()][
            "candidate"].value_counts()
        n_windows = s.window_start.nunique()
        lines.append(f"## {sleeve} (3Y 창 {n_windows}개)")
        lines.append("| 후보 | CAGR 중앙값 | CAGR 최악 | MDD 중앙값 | MDD 최악 |"
                     " Calmar 중앙값 | Calmar 우승 | CAGR 우승 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for label in s.candidate.unique():
            c = s[s.candidate == label]
            lines.append(
                f"| {label} | {c.cagr.median():+.3f} | {c.cagr.min():+.3f} |"
                f" {c.mdd.median():+.3f} | {c.mdd.min():+.3f} |"
                f" {c.calmar.median():.2f} |"
                f" {calmar_wins.get(label, 0)}/{n_windows} |"
                f" {cagr_wins.get(label, 0)}/{n_windows} |"
            )
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[3y] done → {out_dir} (rows={len(rows)})", flush=True)


if __name__ == "__main__":
    main()
