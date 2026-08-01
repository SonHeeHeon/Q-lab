"""AI 상담 프롬프트 빌더 — LLM 무호출, 정적 템플릿 + 실시간 계좌 데이터.

사용자가 폰에서 Claude/GPT 등에 복붙해 포트폴리오 진단을 받는 용도.
템플릿 틀(역할·퀀트 체계 컨텍스트·질문·답변 형식)은 2026-08-01 Claude Fable이
1회 작성해 박제한 것 — 이후에는 버튼 클릭 시점의 데이터 블록만 갱신된다
(API 비용 0). 체계가 크게 바뀌면 이 파일의 정적 텍스트를 사람이 갱신한다.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select

from shared.db.models import AccountProfile, OrderProposal
from shared.db.session import service_session

# ── 정적 컨텍스트 (Fable 작성 — 우리 퀀트 체계 요약) ─────────────────────────
_SYSTEM_CONTEXT = """\
당신은 한국 개인 투자자의 포트폴리오를 진단하는 신중한 자문가입니다. 아래
운용 체계와 현재 계좌 데이터를 읽고, 요청 사항에 답해 주세요. 과신 없이,
불확실한 부분은 불확실하다고 말해 주세요.

## 운용 체계 (배경)
- 규칙 기반 퀀트로 계좌별 분리 운용. 모든 주문은 승인형 반자동(제안 → 사람
  승인 → 실행)이며 자동 전량 매매는 없음.
- 슬리브(전략 단위): KR주식=멀티팩터(밴드트림 1.4), KR ETF=듀얼 모멘텀
  로테이션(절대모멘텀 게이트+손절 -15%), US주식=밸류(손절 -20%),
  US ETF=GTAA 로테이션(게이트, 메뉴에 채권·금 포함). DC/IRP=위험 로테이션
  68%+단기채 32%(위험자산 규제 ≤70%), 연금저축=위험 로테이션 100%.
- 개인(과세) 계좌 목표 비중: US주식 50 / US ETF 40 / KR주식 10 (%).
  **2029-12에 개인 계좌 전액 현금화 예정** — 2029년 글라이드패스(1월 80%→
  7월 50%→10월 20% 위험 축소)와 연 250만원 양도세 공제 활용 분할 실현 계획.
- 신규 자금은 시장 국면 따라 자동 분할 진입(급락 후=올인, 조정=분할).
- 세금: KR 주식 매매차익 비과세(거래세만), KR 과세 ETF 15.4%, US 양도세
  연간 손익통산 후 250만원 공제 초과분 22%, 연금 계좌는 과세이연.
"""

_QUESTIONS = """\
## 요청 사항
위 데이터 기준으로 다음을 진단해 주세요:
1. **리스크**: 지금 포트폴리오에서 가장 큰 리스크 2~3개 (집중도·환율·시점 등)
2. **개선점**: 비중·구성에서 조정을 검토할 만한 것 (목표 비중 대비 이탈 포함)
3. **세금 관점**: 지금 시점에 실행하면 좋은 절세 행동이 있는지
4. **2029-12 청산 계획** 관점에서 지금 준비할 것
5. 위 체계 자체의 맹점이 있다면 지적

## 답변 형식
- 항목별로 나눠서, 각 항목 3문장 이내로 간결하게.
- 구체적 실행 제안은 "무엇을·얼마나·왜" 형태로.
- 매수/매도 종목 추천이 아니라 구조 진단에 집중해 주세요.
"""


def _fmt_krw(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}원"


def _account_line(acct) -> str:
    label = f"{acct.broker.value if hasattr(acct.broker, 'value') else acct.broker}"
    if acct.account_type:
        atype = (
            acct.account_type.value
            if hasattr(acct.account_type, "value")
            else acct.account_type
        )
        label += f" {atype}"
    return (
        f"- {label}: 평가 {_fmt_krw(float(acct.total_value or 0))}, "
        f"손익 {_fmt_krw(float(acct.total_pl or 0))} "
        f"({float(acct.total_pl_pct or 0):+.2f}%)"
    )


async def build_ai_prompt() -> str:
    """버튼 클릭 시점의 계좌 현황으로 프롬프트 완성 (LLM 호출 없음)."""
    # 순환 import 회피 — 엔드포인트 함수를 직접 재사용(모의 제외 통합 뷰)
    from backend.app.api.portfolio import get_unified_portfolio
    from backend.app.services.accounts.profiles import ensure_account_profiles
    from backend.app.services.kis.rest_client import KISRestClient

    async with service_session() as session:
        envelope = await get_unified_portfolio(
            kis_client=KISRestClient(),
            broker="ALL",
            exclude_paper=True,
            session=session,
        )
    portfolio = envelope.data

    async with service_session() as session:
        await ensure_account_profiles(session)
        profiles = (
            (await session.execute(select(AccountProfile))).scalars().all()
        )
        pending = (
            await session.execute(
                select(func.count())
                .select_from(OrderProposal)
                .where(OrderProposal.status == "PROPOSED")
            )
        ).scalar() or 0

    lines: list[str] = [_SYSTEM_CONTEXT]
    lines.append("## 현재 데이터 (생성 시각: "
                 f"{datetime.now().strftime('%Y-%m-%d %H:%M')})")
    lines.append(
        f"- 총 평가액(모의 제외, 원화 환산): {_fmt_krw(float(portfolio.total_value or 0))}"
        f" · 총 손익 {_fmt_krw(float(portfolio.total_pl or 0))}"
        f" ({float(portfolio.total_pl_pct or 0):+.2f}%)"
    )
    if portfolio.fx_rate:
        lines.append(f"- 적용 환율(USD/KRW): {float(portfolio.fx_rate):,.1f}")

    lines.append("\n### 계좌별 요약")
    for acct in portfolio.accounts:
        lines.append(_account_line(acct))

    lines.append("\n### 보유 종목 (계좌 · 종목 · 수량 · 평가액/손익률)")
    if not portfolio.positions:
        lines.append("- 보유 없음")
    for pos in portfolio.positions[:40]:
        value = float(pos.evaluation_amount or 0) or (
            float(pos.current_price or pos.avg_buy_price or 0)
            * int(pos.quantity or 0)
        )
        currency = "$" if (pos.market_country or "KR").upper() == "US" else "₩"
        lines.append(
            f"- {pos.broker.value if hasattr(pos.broker, 'value') else pos.broker}"
            f"{('/' + str(pos.account_type)) if pos.account_type else ''}"
            f" · {pos.name or pos.stock_code}({pos.stock_code})"
            f" · {pos.quantity}주 · {currency}{value:,.0f}"
            f" ({float(pos.unrealized_pl_rate or 0):+.1f}%)"
        )
    if len(portfolio.positions) > 40:
        lines.append(f"- … 외 {len(portfolio.positions) - 40}종목")

    lines.append("\n### 퀀트 운용 상태 (계좌 프로파일)")
    for profile in profiles:
        if profile.account_key == "KIS:PAPER":
            continue  # 모의는 진단 대상 아님
        sleeves = json.loads(profile.sleeves_json)
        sleeve_txt = ", ".join(
            f"{s.get('name') or '고정보유 ' + str(s.get('code'))}"
            f" {s['weight']:.0%}"
            for s in sleeves
        )
        ramp = profile.ramp_in_months
        ramp_txt = "자동" if ramp == -1 else ("안 함" if ramp == 0 else f"{ramp}개월")
        lines.append(
            f"- {profile.account_key}({profile.profile_type}): "
            f"퀀트 {'ON' if profile.quant_enabled else 'OFF'}"
            f" · 슬리브 [{sleeve_txt}] · 분할진입 {ramp_txt}"
        )
    lines.append(f"- 승인 대기 중 제안: {pending}건")
    if portfolio.errors:
        lines.append(f"- (조회 실패 계좌 {len(portfolio.errors)}건 — 미연결 등)")

    lines.append("")
    lines.append(_QUESTIONS)
    return "\n".join(lines)
