"""개인 계좌 2029-12 전액 청산 대응 — 글라이드패스 롤링 검증.

사용자 확정 비중 [KR주식10 / KR_ETF0 / US주식50 / US_ETF40] + 안전(원화 단기채
153130)을 5번째 슬리브로 두고, 41개월(2026-08~2029-12 길이) 롤링 윈도우마다
글라이드패스 스케줄별 종료 NAV·마지막 1년 MDD 분포를 비교한다.

정직 노트: 미래(2026~2029) 백테스트가 아니라 "스케줄 형태"의 과거 분포 비교다.
안전자산=원화 단기채 = 2029-12 원화 현금 수요에 대한 환리스크 제거를 겸한다.

Usage: python research/scripts/plan_2029_glidepath.py
Output: research/reports/matrix/glidepath_<ts>/summary.md
"""
from __future__ import annotations

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
    blend_curves_schedule,
    normalize_curve,
)
from research.backtest.tax_kr import default_tax_model_for_universe  # noqa: E402

START, END = date(2016, 7, 1), date(2026, 7, 1)
WINDOW_MONTHS = 41  # 2026-08 ~ 2029-12
SAFE_CODE = "153130"  # KODEX 단기채권(원화) — 환리스크 없는 청산용 안전자산
SLEEVES = [("KR주식", "qlab_alpha_v2"), ("KR_ETF", "etf_rotation_kr"),
           ("US주식", "us_value"), ("US_ETF", "etf_rotation_us")]
BASE_W = [0.10, 0.00, 0.50, 0.40]  # 사용자 확정(2026-07-29)

# 스케줄: (윈도우 시작 후 개월, risky 비율). risky는 BASE_W 비례 배분, 나머지=안전.
GLIDES: dict[str, list[tuple[int, float]]] = {
    "baseline_no_glide": [(0, 1.0)],
    "glide_18m": [(0, 1.0), (23, 0.85), (29, 0.60), (35, 0.30), (38, 0.10)],
    "glide_12m": [(0, 1.0), (29, 0.80), (35, 0.50), (38, 0.20)],
}


def _safe_curve() -> pd.Series:
    with sqlite3.connect(research_db_path) as conn:
        rows = conn.execute(
            "SELECT date, close FROM prices_daily WHERE stock_code = ?"
            " ORDER BY date", (SAFE_CODE,),
        ).fetchall()
    if not rows:
        raise SystemExit(f"안전자산 {SAFE_CODE} 가격 없음")
    return normalize_curve([(date.fromisoformat(r[0]), float(r[1])) for r in rows])


def _add_months(day: date, months: int) -> date:
    y, m = divmod(day.year * 12 + (day.month - 1) + months, 12)
    return date(y, m + 1, 1)


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "research" / "reports" / "matrix" / f"glidepath_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    fx = _usdkrw_index(None)
    curves = []
    for _, name in SLEEVES:
        strat = load_strategy(name).model_copy(
            update={"start_date": START, "end_date": END})
        res = run_backtest(
            strat, tax_model=default_tax_model_for_universe(strat.universe))
        curves.append(apply_krw_view(
            normalize_curve(res.equity_curve), strat.universe, fx))
        print(f"[glide] curve ready: {name}", flush=True)
    curves.append(_safe_curve())

    def weights_at(risky: float) -> list[float]:
        return [w * risky for w in BASE_W] + [1.0 - risky]

    results: dict[str, list[dict]] = {g: [] for g in GLIDES}
    win_start = START
    while _add_months(win_start, WINDOW_MONTHS) <= END:
        win_end = _add_months(win_start, WINDOW_MONTHS)
        for gname, glide in GLIDES.items():
            schedule = [(_add_months(win_start, m), weights_at(r)) for m, r in glide]
            pts = [(d, v) for d, v in blend_curves_schedule(
                curves, schedule, base_nav=1.0) if d < win_end]
            if len(pts) < 200:
                continue
            final_year = [(d, v) for d, v in pts if d >= _add_months(win_end, -12)]
            m_last = compute_metrics(final_year, []) if len(final_year) > 20 else None
            results[gname].append({
                "start": win_start.isoformat(), "terminal": round(pts[-1][1], 4),
                "final_year_mdd": round(m_last.mdd, 4) if m_last else None,
            })
        win_start = _add_months(win_start, 3)

    lines = ["# 2029-12 글라이드패스 롤링 비교 (41개월 윈도우, 3개월 스텝)", "",
             f"- 기본 비중 {BASE_W} + 안전({SAFE_CODE}) / 월간 리셋 / 세후·KRW 관점", "",
             "| 스케줄 | 윈도우 수 | 종료NAV 최악 | 중앙값 | 최고 | 최악 마지막1년 MDD |",
             "|---|---|---|---|---|---|"]
    for gname, rows in results.items():
        if not rows:
            continue
        terms = sorted(r["terminal"] for r in rows)
        mdds = [r["final_year_mdd"] for r in rows if r["final_year_mdd"] is not None]
        lines.append(
            f"| {gname} | {len(rows)} | {terms[0]:.3f} |"
            f" {terms[len(terms) // 2]:.3f} | {terms[-1]:.3f} |"
            f" {min(mdds):.3f} |")
    lines += ["", "## 세금 분할 매도 (산술)",
              "- 미국 양도세 기본공제 연 250만원 → 2029-12 일괄 매도 대신"
              " 2027/2028/2029 3개 연도 분할 실현 시 공제 3회 활용:"
              " 절세액 ≈ 0.22 × 250만 × 2 = **약 110만원** (각 해 실현이익이"
              " 250만원 이상일 때; 이익이 작으면 그 이하).",
              "- 실행 규칙: 글라이드패스의 위험 축소분 매도를 연도 경계에 맞춰"
              " 분산(12월/1월 걸치기)한다.",
              "## 환리스크 규칙",
              f"- 안전 전환분은 전부 원화 단기채({SAFE_CODE}) — 2029-12 원화 현금"
              " 수요에 대한 통화 일치. USD 자산은 글라이드 단계에서 순차 청산."]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[glide] done → {out_dir}", flush=True)


if __name__ == "__main__":
    main()
