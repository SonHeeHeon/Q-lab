# KR ETF 유니버스 확장 — 실환경 런북

> **[2026-07-26 정정]** 당초 "이 환경의 최근 시세는 합성(mock)"으로 진단했으나, **KIS
> 실서버 현재가 대조로 데이터가 실재함을 확인**했다(삼성전자 KIS=249,500 == DB, ETF
> 상장일도 실제와 일치). 죽어 있는 것은 **pykrx의 KRX 데이터포털 엔드포인트뿐**(ETF
> 목록 열거·구성종목 PDF — pykrx/KRX API 호환성 문제로 추정). 따라서 시세 적재
> (Naver 경로)와 백테스트 검증은 **이 환경에서 유효**하며, 아래 절차 중 KRX 엔드포인트
> 의존 단계(2. 세금 자동분류)만 pykrx 복구 또는 KIS API 대체 구현이 필요하다.

## 0. 전제
- 실 KRX/pykrx 접근이 되는 환경(정상 시계). `.venv` 활성, `KRX_ID`/`KRX_PW` 설정(필요 시).
- 큐레이션 목록: `data/manual/kr_etf_universe.csv`(27종). **코드가 실제 ETF와 맞는지 먼저 검토**
  (샌드박스에선 검증 불가였음 — `pykrx.stock.get_etf_ticker_list()`로 대조 권장).

## 1. ETF 시세 적재 (신규 ~17종)
```bash
# dry-run으로 먼저 확인
python research/scripts/seed_kr_etfs.py --dry-run
# 실제 적재(전 구간 백필). 실환경이면 실데이터가 들어온다.
python research/scripts/seed_kr_etfs.py --start 2016-01-01
```
- stocks(market='ETF') 행 upsert 후 prices_daily 백필. **시세 조회 실패 코드는 자동 스킵**
  → 스킵 목록을 보고 잘못된 코드를 `kr_etf_universe.csv`에서 교정 후 재실행.
- 이후 일일 `data_sync`(18:00)가 자동으로 최신화(신규 코드는 마지막 날짜부터 이어받음).

## 2. 세금 자동분류 (수동 CSV 보완)
큐레이션 27종은 이미 `kr_etf_tax_class.csv`에 수동 분류돼 있음. **새로 추가하는 ETF**만:
```bash
python -c "
from research.data_ingestion.etf_tax_classifier import build_auto_tax_csv
from pathlib import Path
codes = ['새코드1','새코드2']   # 추가한 ETF 코드
build_auto_tax_csv(codes, Path('data/manual/kr_etf_tax_class.auto.csv'))
"
```
- 구성종목(deposit file)이 국내 상장주식 위주면 `domestic_equity`(비과세), 아니면 `taxable`(15.4%).
- `tax_kr`이 `{**auto, **manual}`로 병합 — **수동 CSV가 항상 우선**. 애매하면 수동 CSV에 직접 명시.

## 3. 절대 모멘텀 게이트 검증 (채택 전 필수)
게이트는 **OFF로 출하**됨. 켜기 전에 실데이터로 walk-forward OOS 검증:
```bash
python research/scripts/validate_absmom.py --strategy etf_rotation_kr
# 출력: research/reports/matrix/absmom_validation_<ts>/{results.csv, summary.md}
```
- **채택 규칙(방어용)**: OOS에서 baseline 대비 Sharpe 개선 **또는** MDD 큰 개선∧Sharpe 유지가
  **일관될 때만**. 한 기간만 좋고 다른 기간 악화면 미채택.
- summary.md의 경고 배너대로, **인-샘플 수치는 참고용**. OOS·실데이터가 근거.

## 4. 게이트 켜기 (검증 통과 시에만)
`research/strategies/etf_rotation_kr.yaml`(또는 private 사본)에 추가:
```yaml
abs_momentum_gate: true          # 자기 12M 모멘텀<=0 종목 제외, 빈 슬롯 현금
abs_momentum_factor: MOMENTUM_12M
```
백테스트·라이브 제안이 동일 로직으로 게이트 적용(E5 패리티). ETF 슬리브 월초 리밸런스에서 발동.

## 5. 유동성/레버리지 가드레일 (이미 적용됨)
- `etf_rotation_kr.yaml`에 `TURNOVER_PROXY ≥ ₩1억` 필터(거래 불가 종목 배제).
- `get_universe("ETF_KR")`가 레버리지/인버스(레버리지·인버스·곱버스·2X) 이름을 자동 제외.
  선물/(H) 헤지형(골드선물·달러선물·S&P선물)은 단일 익스포저라 유지.

## 알려진 한계 (정직)
- **분배금(배당) 미반영**: ETF adj_close==close(pykrx 저장 특성) → 모멘텀·성과가 가격수익 기준.
  채권·인컴·커버드콜 ETF가 체계적으로 저평가됨. 분배금 적재는 별도 백로그.
- **코드 정확성**: 큐레이션 목록은 리드 작성 템플릿 — 실환경에서 열거로 최종 대조 필요.
- **US 종목 매수등급/세금**: 별도(2슬리브 리포트 참고). 여기선 KR ETF 유니버스만 다룸.

관련: `.omc/reports/2026-07-25_etf-universe-expansion.md`, `.omc/plan/2026-07-25_etf-universe-expansion.md`.
