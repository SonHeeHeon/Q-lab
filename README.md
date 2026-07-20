# Q-Lab: 개인용 퀀트 리서치 + 자동매매 실험실

Q-Lab은 개인 투자자가 직접 데이터를 모으고, 투자 아이디어를 검증하고,
실제 계좌와 연결해 모의/자동 매매까지 실험할 수 있도록 만든 로컬 우선
증권 애플리케이션입니다.

이 프로젝트는 네 가지 흐름을 하나로 묶습니다.

```text
KRX/DART/KIS/Toss/yfinance 데이터
        |
        v
research.db / service.db
        |
        +--> Jupyter / 팩터 연구 / 백테스트 / Optuna 최적화
        |
        +--> FastAPI 백엔드
                |
                +--> Flutter 앱: 포트폴리오, 히트맵, 관심종목, 매매일지
                |
                +--> Broker APIs: KIS + Toss 잔고, 주문, 시세, 주문 동기화
                |
                +--> LLM/Telegram: 일일 리포트, 투자 원칙 위반 복기
```

핵심 목표는 단순합니다.

- 데이터를 모읍니다: KOSPI200, KOSDAQ150, KOSDAQ 전체, NASDAQ100 가격과 재무 데이터
- 전략을 연구합니다: PER, PBR, ROE 같은 팩터와 사용자 정의 전략
- 검증합니다: point-in-time 백테스트, walk-forward, Optuna 최적화
- 운영합니다: KIS/Toss 잔고와 주문, 주문 체결 추적, 외부 주문 동기화
- 복기합니다: LLM이 매매일지와 투자 원칙을 함께 읽고 위반 여부를 요약

`PROJECT_BLUEPRINT.md`는 설계 원본이고, 이 문서는 실제 실행 가이드입니다.

## 1. 서비스 소개 및 핵심 가치

Q-Lab은 “투자 아이디어를 감으로 끝내지 않고, 데이터와 기록으로 검증하자”는
목적으로 만들어졌습니다.

주요 기능은 다음과 같습니다.

| 영역 | 설명 |
|---|---|
| 데이터 수집 | pykrx, DART, yfinance를 사용해 가격/재무 데이터를 `research.db`에 적재 |
| 리서치 | Jupyter Notebook에서 팩터, 회귀식, 마법공식, 사용자 전략 실험 |
| 백테스트 | 거래비용, 세금, 슬리피지를 반영한 현실적인 백테스트 |
| 최적화 | Optuna로 가치 팩터 가중치 탐색 |
| 실시간 화면 | FastAPI와 Flutter로 포트폴리오, 관심종목, 히트맵, 퀀트 탭 제공 |
| 멀티 브로커 | 한국투자증권(KIS)과 토스증권 Open API를 공통 브로커 인터페이스로 연결 |
| 자동화 | 장 마감 후 분석, 일일 리포트, 외부 주문 동기화, macOS LaunchAgent |
| 안전장치 | Mock 기본값, 주문 추적, 리스크 매니저, LLM 토큰 예산 제한 |

장중 히트맵은 두 가지 경로를 사용합니다.

```text
08:00~20:00, 평일 KOSPI 요청
        -> KIS REST 현재가를 5분마다 메모리에 캐싱
        -> /api/heatmap?market=KOSPI 에서 실시간 스냅샷 반환

그 외 시간, KOSDAQ 요청, 또는 as_of 지정 요청
        -> research.db의 일봉/전일 종가 기준 히트맵 반환
```

히트맵 응답에는 `updated_at`, `market_session`, `source`가 포함됩니다.

시장 세션 구분은 다음과 같습니다.

| 시간 | 세션 |
|---|---|
| 08:00~08:59 | `PRE_MARKET` |
| 09:00~15:30 | `REGULAR` |
| 15:31~20:00 | `AFTER_HOURS` |
| 그 외 시간/주말 | `CLOSED` |

## 2. 설치 및 시작 가이드

### 2.1 Python 백엔드 설치

```bash
cd /Users/honey/Dev/StockCollect_Project
python -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
```

`.env`에 KIS, DART, OpenAI 등 필요한 값을 채웁니다. 실제 `.env`는 Git에
올라가지 않습니다.

### 2.2 DB 마이그레이션

```bash
.venv/bin/python -m alembic --name service upgrade head
.venv/bin/python -m alembic --name research upgrade head
```

생성되는 파일:

```text
data/service.db    앱, 계좌, 주문, 매매일지, 설정
data/research.db   가격, 재무제표, 백테스트용 데이터
```

### 2.3 백엔드 실행

개발 중에는 자동 작업을 잠시 끄고 실행하는 편이 조용합니다.

```bash
KIS_WS_AUTOSTART=false \
BATCH_SCHEDULER_AUTOSTART=false \
ORDER_TRACKER_AUTOSTART=false \
MARKET_SNAPSHOT_AUTOSTART=false \
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Swagger 문서:

```text
http://127.0.0.1:8000/docs
```

장중 실시간 KOSPI 히트맵을 켜려면:

```bash
MARKET_SNAPSHOT_AUTOSTART=true \
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

### 2.4 Flutter 프론트엔드 실행

```bash
cd app
flutter pub get
flutter run -d chrome
```

프론트엔드는 `http://127.0.0.1:8000`의 FastAPI 백엔드를 호출합니다.
CORS는 로컬 개발 포트를 허용하도록 설정되어 있습니다.

### 2.5 Jupyter 리서치 환경 실행

```bash
backend/scripts/run_jupyter.sh
```

시작 노트북:

```text
research/notebooks/01_factor_exploration.ipynb
research/notebooks/02_data_visualization.ipynb
```

## 3. 환경 변수(.env) 명세서

`.env.example`을 복사한 뒤 실제 값을 `.env`에만 입력합니다.

### 3.1 필수 설정 값

| 변수 | 필수 상황 | 설명 |
|---|---:|---|
| `KIS_PAPER_APP_KEY` | KIS 모의투자 사용 | 한국투자증권 모의투자 앱 키 |
| `KIS_PAPER_APP_SECRET` | KIS 모의투자 사용 | 한국투자증권 모의투자 앱 시크릿 |
| `KIS_PAPER_ACCOUNT_NO` | KIS 모의투자 사용 | 모의투자 계좌번호 |
| `KIS_REAL_APP_KEY` | 실전 일반 계좌 사용 | 한국투자증권 실전 앱 키 |
| `KIS_REAL_APP_SECRET` | 실전 일반 계좌 사용 | 한국투자증권 실전 앱 시크릿 |
| `KIS_REAL_ACCOUNT_NO` | 실전 일반 계좌 사용 | 실전 일반 계좌번호 |
| `KIS_ISA_APP_KEY` | ISA 계좌 사용 | ISA용 앱 키 |
| `KIS_ISA_APP_SECRET` | ISA 계좌 사용 | ISA용 앱 시크릿 |
| `KIS_ISA_ACCOUNT_NO` | ISA 계좌 사용 | ISA 계좌번호 |
| `DART_API_KEY` | 한국 재무 데이터 수집 | DART OpenAPI 인증키 |
| `OPENAI_API_KEY` | LLM 리포트/매매일지 분석 | OpenAI API 키 |

처음에는 `PAPER` 계좌만 채워도 대부분의 조회/모의 기능을 테스트할 수 있습니다.

### 3.2 KIS 및 실시간 시세 설정

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `KIS_DEFAULT_ACCOUNT` | `PAPER` | 기본 KIS 계좌 타입 |
| `KIS_SSL_VERIFY` | `true` | KIS HTTPS 인증서 검증 |
| `KIS_CA_BUNDLE_PATH` | 빈 값 | 사설 CA 인증서 파일 경로 |
| `KIS_WS_AUTOSTART` | `true` | KIS 실시간 체결 WebSocket 자동 시작 |
| `KIS_WS_DEFAULT_CODES` | `005930` | 기본 실시간 구독 종목 |
| `KIS_WS_RECONNECT_MAX_SECONDS` | `60` | WebSocket 재연결 최대 대기 |
| `MARKET_SNAPSHOT_AUTOSTART` | `true` | 장중 KOSPI200 히트맵 스냅샷 자동 갱신 |
| `MARKET_SNAPSHOT_ACCOUNT_TYPE` | `PAPER` | 현재가 조회에 사용할 계좌 타입 |
| `MARKET_SNAPSHOT_INTERVAL_MINUTES` | `5` | 장중 히트맵 갱신 주기 |
| `MARKET_SNAPSHOT_REQUEST_CONCURRENCY` | `8` | KIS 현재가 병렬 조회 개수 |
| `MARKET_SNAPSHOT_STALE_AFTER_MINUTES` | `10` | API 요청 시 캐시를 오래된 것으로 볼 기준 |
| `MARKET_SESSION_PRE_MARKET_START` | `08:00` | ATS 장전 세션 시작 |
| `MARKET_SESSION_PRE_MARKET_END` | `08:50` | ATS 장전 세션 종료 |
| `MARKET_SESSION_REGULAR_START` | `09:00` | 정규장 시작 |
| `MARKET_SESSION_REGULAR_END` | `15:30` | 정규장 종료 |
| `MARKET_SESSION_AFTER_HOURS_START` | `15:30` | ATS 시간외 세션 시작 |
| `MARKET_SESSION_AFTER_HOURS_END` | `20:00` | ATS 시간외 세션 종료 |

KIS 키가 아직 없다면 `KIS_WS_AUTOSTART=false`,
`MARKET_SNAPSHOT_AUTOSTART=false`로 두고 백엔드를 시작하세요.

### 3.3 Toss Open API 설정

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `TOSS_API_BASE_URL` | `https://openapi.tossinvest.com` | 토스증권 Open API 서버 |
| `TOSS_CLIENT_ID` | 빈 값 | OAuth2 client credentials용 client id |
| `TOSS_CLIENT_SECRET` | 빈 값 | OAuth2 client credentials용 client secret |
| `TOSS_ACCOUNT_SEQ` | 빈 값 | 주문/잔고 조회에 사용할 토스 `accountSeq`; 비우면 계좌 목록 첫 종합매매 계좌 사용 |
| `TOSS_IS_MOCK` | `true` | `true`면 토스 주문을 실제 전송하지 않고 mock 주문번호만 반환 |
| `TOSS_HTTP_TIMEOUT_SECONDS` | `10` | Toss REST 요청 타임아웃 |
| `TOSS_SSL_VERIFY` | `true` | Toss HTTPS 인증서 검증 |
| `TOSS_CA_BUNDLE_PATH` | 빈 값 | 사설 CA 인증서 파일 경로 |

토스 Open API 1.1.1 명세에는 WebSocket이 아직 제공되지 않습니다. 따라서
토스 실시간성 데이터는 현재 REST 현재가 조회를 사용하며, `ws_client.py`는
미지원 상태를 명확히 알려주는 안전한 placeholder로 둡니다.

### 3.4 자동매매 및 안전장치

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `ORDER_TRACKER_AUTOSTART` | `true` | 앱에서 제출한 주문 체결 상태 자동 추적 |
| `ORDER_TRACKER_POLL_INTERVAL_SECONDS` | `30` | 주문 상태 폴링 주기 |
| `ORDER_TRACKER_ORDER_TIMEOUT_SECONDS` | `300` | 오래된 미체결 주문 타임아웃 기준 |
| `AUTOMATION_KILL_SWITCH` | `false` | `true`면 live 자동 주문을 차단 |
| `AUTOMATION_MAX_ORDER_VALUE` | `5000000` | live 자동 주문 1건 최대 추정 금액 |
| `AUTOMATION_MAX_DAILY_LOSS_PCT` | `-5.0` | 운영자가 참고할 일일 손실 한도 기준 |
| `REBALANCER_IS_MOCK` | `true` | 리밸런서 주문을 실제 발송하지 않고 로그만 남김 |
| `REBALANCER_MIN_TRADE_VALUE` | `50000` | 최소 주문 금액 |
| `REBALANCER_CASH_BUFFER_PCT` | `0.005` | 현금 버퍼 비율 |
| `RISK_MANAGER_AUTOSTART` | `false` | 실시간 손절 워커 자동 시작 |
| `RISK_MANAGER_IS_MOCK` | `true` | 손절 주문을 실제 발송하지 않음 |
| `RISK_MANAGER_ACCOUNT_TYPE` | `PAPER` | 리스크 매니저 대상 계좌 |
| `RISK_MANAGER_STOP_LOSS_PCT` | `-10.0` | 자동 손절 기준 |
| `RISK_MANAGER_POSITION_REFRESH_SECONDS` | `60` | 보유종목 새로고침 주기 |

실전 주문 전에는 반드시 `PAPER`에서 충분히 검증하세요.
운영 중 즉시 자동 주문을 멈추려면 `POST /api/automation/kill-switch`로
kill switch를 켤 수 있습니다.

### 3.5 LLM 및 텔레그램

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `LLM_PROVIDER` | `openai` | LLM 제공자 |
| `LLM_MODEL` | `gpt-4o` | 사용할 모델명 |
| `LLM_DAILY_TOKEN_BUDGET` | `200000` | 하루 LLM 토큰 예산 상한 |
| `LLM_CACHE_TTL_HOURS` | `24` | 동일 프롬프트 캐시 유지 시간 |
| `TELEGRAM_BOT_TOKEN` | 빈 값 | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 빈 값 | 메시지를 받을 채팅 ID |
| `TELEGRAM_SSL_VERIFY` | `true` | 텔레그램 HTTPS 인증서 검증 |
| `TELEGRAM_CA_BUNDLE_PATH` | 빈 값 | 텔레그램용 사설 CA 파일 경로 |

데이터 수집과 Optuna 최적화 루프는 LLM을 호출하지 않습니다. LLM은 일일 리포트,
매매일지 분석 등 명시된 서비스에서만 사용됩니다.

### 3.6 데이터, 스케줄러, 기타

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `SERVICE_DB_PATH` | `data/service.db` | 서비스 DB 경로 |
| `RESEARCH_DB_PATH` | `data/research.db` | 리서치 DB 경로 |
| `TOKEN_CACHE_DIR` | `data/tokens` | KIS/Toss 토큰 캐시 |
| `LLM_CACHE_DIR` | `data/cache` | LLM/기타 캐시 |
| `BATCH_SCHEDULER_AUTOSTART` | `false` | 일일 분석/리포트/외부 주문 동기화 자동 실행 |
| `APSCHEDULER_TIMEZONE` | `Asia/Seoul` | 스케줄러 시간대 |
| `DAILY_ANALYSIS_CRON` | `30 16 * * MON-FRI` | 일일 저평가 종목 분석 시각 |
| `DAILY_REPORT_CRON` | `45 16 * * MON-FRI` | LLM 리포트 발송 시각 |
| `DATA_SYNC_CRON` | `0 18 * * MON-FRI` | 데이터 동기화 예약용 |
| `BROKER_ORDER_SYNC_CRON` | `10 16 * * MON-FRI` | 한투 앱/HTS 외부 주문 동기화 시각 |
| `BROKER_ORDER_SYNC_LOOKBACK_DAYS` | `7` | 외부 주문 조회 기본 기간 |
| `BROKER_ORDER_SYNC_ACCOUNTS` | `PAPER,REAL,ISA` | 외부 주문 동기화 대상 계좌 |
| `DEFAULT_STRATEGY_NAME` | `value_v1` | 기본 전략 이름 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |
| `LOG_DIR` | `logs/backend` | 백엔드 로그 경로 |
| `LOG_BACKUP_DAYS` | `14` | 로그 보관 일수 |
| `TZ` | `Asia/Seoul` | 기본 시간대 |
| `KRX_ID`, `KRX_PW` | 빈 값 | pykrx/KRX 환경에서 인증이 필요할 때 사용 |

### 3.7 원격 접근 / 배포 (개인 폰에서 접속할 때)

localhost 밖(예: 개인 폰)으로 백엔드를 노출할 때만 필요합니다. 기본값은 로컬
단일 사용자용으로 인증이 꺼져 있어, 아래를 비워두면 기존 동작 그대로입니다.

| 변수 | 기본값 | 설명 |
|---|---:|---|
| `BACKEND_API_KEY` | 빈 값 | **비우면 인증 OFF**(로컬 기본). 값을 넣으면 `/health`·`/docs`를 뺀 모든 요청에 `Authorization: Bearer <키>` 또는 `X-API-Key: <키>`가 필요. 상수시간 비교, 로그에 절대 남지 않음 |
| `CORS_ORIGINS` | 빈 값 | 콤마 구분 추가 허용 오리진. **Flutter '웹' 빌드를 브라우저로 쓸 때만** 필요(네이티브 앱은 무관). 예: `https://qlab.my-tailnet.ts.net` |

> 로컬 개발 중에는 `BACKEND_API_KEY`를 비워 두세요. 값을 넣으면 로컬 프론트도
> 그 키를 보내야 하므로(안 그러면 전부 `401`), 폰에 실제로 노출할 때만 설정합니다.
> 자세한 배포 절차는 아래 6장을 참고하세요.

## 4. 사용자 맞춤형 단계별 가이드

### 4.1 1단계: 포트폴리오와 잔고 조회만 쓰는 사용자

목표: KIS 또는 Toss 계좌를 연결해 잔고, 보유종목, 주문 내역 동기화만 사용합니다.

1. KIS를 쓰면 `.env`에 `KIS_PAPER_*` 값을 입력합니다.
2. Toss를 쓰면 `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET`, 필요 시 `TOSS_ACCOUNT_SEQ`를 입력합니다.
3. 백엔드를 실행합니다.
4. Swagger에서 잔고를 확인합니다.

```bash
curl -s http://127.0.0.1:8000/api/portfolio/PAPER | python -m json.tool
curl -s 'http://127.0.0.1:8000/api/portfolio?broker=TOSS' | python -m json.tool
```

한투 앱/HTS에서 직접 낸 주문을 가져오려면:

```bash
curl -s -X POST http://127.0.0.1:8000/api/portfolio/orders/sync \
  -H "Content-Type: application/json" \
  -d '{"account_type":"PAPER"}' | python -m json.tool
```

기본 조회 기간은 최근 7일입니다. 더 길게 보려면 요청에 날짜를 넣습니다.

```json
{
  "account_type": "PAPER",
  "start_date": "2026-05-01",
  "end_date": "2026-06-09"
}
```

### 4.2 2단계: 팩터 연구와 백테스트 중심 사용자

목표: 데이터를 모으고 Jupyter/백테스트/Optuna로 전략을 연구합니다.

KOSPI200 10년치 데이터:

```bash
.venv/bin/python research/scripts/download_universe.py \
  --universe KOSPI200 \
  --years 10 \
  --price-concurrency 4 \
  --financial-concurrency 2 \
  --pykrx-sleep 0.2 \
  --dart-sleep 0.3
```

KOSDAQ150 10년치 데이터:

```bash
SQLITE_BUSY_TIMEOUT_SECONDS=120 .venv/bin/python research/scripts/download_universe.py \
  --universe KOSDAQ150 \
  --years 10 \
  --price-concurrency 4 \
  --financial-concurrency 2 \
  --pykrx-sleep 0.2 \
  --dart-sleep 0.3
```

NASDAQ100 10년치 데이터:

```bash
.venv/bin/python research/scripts/download_us_universe.py \
  --universe NASDAQ100 \
  --years 10 \
  --sleep 0.25
```

백테스트:

```bash
.venv/bin/python research/scripts/run_backtest.py \
  --strategy research/strategies/value_v1.yaml \
  --tag smoke
```

Optuna 최적화:

```bash
mkdir -p logs/research
nohup .venv/bin/python -m research.optimization.optuna_runner \
  --strategy research/strategies/value_v1.yaml \
  --trials 100 \
  --objective sharpe \
  --study-name value_v1_sharpe_100 \
  > logs/research/value_v1_optuna_100.log 2>&1 &
tail -f logs/research/value_v1_optuna_100.log
```

### 4.3 3단계: 자동매매와 리스크 매니저까지 쓰는 사용자

목표: 전략 결과를 실제 계좌와 비교하고, 자동 리밸런싱/손절 안전장치를 실험합니다.

권장 순서:

1. `PAPER` 계좌만 연결합니다.
2. `REBALANCER_IS_MOCK=true`, `RISK_MANAGER_IS_MOCK=true` 상태에서 로그를 확인합니다.
3. 소액/모의투자에서 주문 결과가 의도와 맞는지 검증합니다.
4. 실전 계좌 설정은 마지막에 진행합니다.

리스크 매니저를 켤 때:

```bash
RISK_MANAGER_AUTOSTART=true
RISK_MANAGER_IS_MOCK=true
RISK_MANAGER_ACCOUNT_TYPE=PAPER
RISK_MANAGER_STOP_LOSS_PCT=-10.0
```

Mock을 끄는 것은 실제 주문 발송을 의미합니다. 실전 전환은 매우 신중하게 해야 합니다.

## 5. 시스템 이용 시 주의사항

### 5.1 SQLite Lock 방지

이 프로젝트는 로컬 SQLite를 사용합니다. 같은 DB를 여러 프로세스가 동시에 쓰면
`database is locked`가 발생할 수 있습니다.

권장 사항:

- 대용량 수집 중에는 FastAPI 서버, Jupyter, DB Browser를 잠시 끕니다.
- KOSDAQ처럼 종목 수가 많을 때는 `SQLITE_BUSY_TIMEOUT_SECONDS=120`을 붙입니다.
- 병렬도를 너무 높이지 않습니다. `--price-concurrency 4` 정도를 권장합니다.

예시:

```bash
SQLITE_BUSY_TIMEOUT_SECONDS=120 .venv/bin/python research/scripts/download_universe.py \
  --universe KOSDAQ150 \
  --years 10 \
  --price-concurrency 4
```

### 5.2 실시간 히트맵 주의

- 장중 KOSPI 히트맵은 KIS REST 현재가를 5분마다 조회합니다.
- 서버가 꺼져 있으면 메모리 캐시도 사라집니다.
- 첫 요청 시 캐시가 비어 있거나 오래되면 API가 한 번 즉시 갱신을 시도할 수 있습니다.
- KIS API 제한이나 네트워크 오류가 있으면 기존 `research.db` 종가 기반 히트맵으로 돌아갈 수 있습니다.

### 5.3 실전 투자 안전장치

기본값은 안전을 우선합니다.

- `REBALANCER_IS_MOCK=true`
- `RISK_MANAGER_AUTOSTART=false`
- `RISK_MANAGER_IS_MOCK=true`
- `BATCH_SCHEDULER_AUTOSTART=false`

실전 주문을 허용하기 전 확인할 것:

- 계좌 타입이 `PAPER`가 아닌지
- 주문 수량과 금액 계산이 맞는지
- 손절 기준이 너무 촘촘하지 않은지
- 텔레그램 알림이 정상 동작하는지
- 장중/시간외 가격 데이터가 실제로 들어오는지

### 5.4 Open Source 공개 주의

공개하면 안 되는 파일:

```text
.env
data/*.db
data/backups/
data/tokens/*.json
logs/
.claude/settings.local.json
research/reports/optuna_studies.db
research/reports/optimization/
research/reports/runs/
```

현재 `.gitignore`는 위 항목을 제외합니다. 공개 전에는 다음 명령으로 한 번 더 확인하세요.

```bash
git ls-files | grep -E '(^\.env$|data/.*\.db|data/tokens/.+\.json|logs/|\.claude/settings.local.json|optuna_studies.db)' || true
```

## 6. Docker 배포 및 개인 폰(모바일) 사용

증권 앱이라 앱스토어에 올릴 수 없으므로, **집의 Mac mini에 백엔드를 상시 띄우고
개인 폰(네이티브 앱)에서 사설망으로 접속**하는 구조를 사용합니다.

### 6.1 전체 구조

```text
┌─────────── Mac mini (집에서 24시간 켜둠) ───────────┐
│  Docker: 백엔드(FastAPI) : 8000   ← 이것만 상시 실행 │
│          + data/service.db · research.db (마운트)    │
└───────────────────┬──────────────────────────────────┘
                    │  Tailscale HTTPS (사설망 · 암호화)
              ┌─────┴─────┐
              │  아이폰    │  Flutter 코드가 '앱에 통째로 구워진'
              │ (네이티브  │  네이티브 앱 → 프론트 서버가 따로 없음.
              │   앱)      │  앱이 백엔드 API 를 직접 호출.
              └───────────┘
```

- **상시 실행되는 것은 백엔드 하나뿐**입니다. 프론트엔드는 서버가 아니라 폰에 설치되는
  앱에 컴파일되어 들어갑니다(그래서 `docker-compose.yml`에도 `backend` 서비스만 있음).
- 폰에서는 **브라우저가 아니라 앱**으로 사용합니다(홈 화면 아이콘).

### 6.2 백엔드 컨테이너 실행 (Mac mini)

```bash
# 1) .env 준비 — 원격 노출 시 BACKEND_API_KEY 를 꼭 설정(6.3)
# 2) service.db 마이그레이션(최초 1회)
.venv/bin/python -m alembic --name service upgrade head
# 3) 빌드 & 상시 기동 (재부팅에도 살아남음: restart=unless-stopped)
docker compose build backend
docker compose up -d backend
docker compose logs -f backend        # /health 200 확인
```

이미지는 `backend/Dockerfile`(python:3.12-slim 멀티스테이지, 비루트, `--reload` 없음,
`/health` healthcheck). 상태 파일(`data/`, `logs/`)만 호스트에서 마운트하고 코드는
이미지에 굽습니다. 연구용 무거운 의존성까지 포함하므로 이미지 용량은 큽니다.

### 6.3 인증 켜기 + 폰 접속 (Tailscale HTTPS 권장)

localhost 밖으로 나가는 순간 API는 **라이브 주문 라우트까지 전부 개방**이므로, 다음이 필수입니다.

1. `.env`에 `BACKEND_API_KEY=<길고 무작위한 문자열>` 설정 → 백엔드 재시작.
2. Mac mini·폰에 **Tailscale** 설치(같은 tailnet). Mac mini에서:
   ```bash
   tailscale serve https / http://localhost:8000
   ```
   → `https://<host>.ts.net` 로 **Let's Encrypt 인증서 자동** 부여. iOS/안드의 평문 차단
   문제를 함께 해결하고, 공개 인터넷 노출 없이 어디서나 사설망 접속.

> LAN IP + http, Cloudflare Tunnel, Caddy 리버스 프록시 등 다른 방법도 가능하나,
> 증권 앱에는 **Tailscale HTTPS + `BACKEND_API_KEY`** 조합을 권장합니다.

### 6.4 아이폰에 설치 (사이드로드, 무료 서명)

**맥에서 빌드**합니다. Tailscale HTTPS면 iOS ATS 예외가 필요 없습니다. 번들 ID는
`com.qlab.personal`로 설정돼 있습니다.

```bash
# (사전 1회) 전체 Xcode.app 설치(App Store) 후:
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -runFirstLaunch
sudo gem install cocoapods            # 또는 brew install cocoapods
flutter doctor                        # Xcode·CocoaPods ✓ 확인

# (서명) Xcode 에서 무료 개인 팀으로 서명
open app/ios/Runner.xcworkspace
#  → Settings > Accounts 에 Apple ID 추가
#  → Runner 타깃 > Signing & Capabilities > "Automatically manage signing" 체크,
#     Team = 본인 Apple ID(Personal Team)

# (아이폰) USB 연결 + "이 컴퓨터 신뢰",
#  설정 > 개인정보보호 및 보안 > 개발자 모드 ON(재부팅)

# (설치) <host>=Tailscale 주소, <키>=BACKEND_API_KEY 와 동일
cd app
flutter run --release \
  --dart-define=API_BASE_URL=https://<host>.ts.net \
  --dart-define=WS_BASE_URL=wss://<host>.ts.net \
  --dart-define=API_KEY=<키>
#  첫 실행 후 아이폰: 설정 > 일반 > VPN 및 기기 관리 > 본인 Apple ID > "신뢰"
```

⚠️ **무료 개인 팀은 서명이 7일 뒤 만료**되어 앱이 안 열립니다 → 매주 `flutter run
--release`로 재설치. 번거로우면 **유료 개발자계정($99/년)** → 1년 유효 + TestFlight
무선 설치.

안드로이드는 `flutter build apk --release` 후 사이드로드(INTERNET 권한·HTTPS 기본
network-config 설정 완료). `--dart-define` 값은 iOS와 동일하게 넣습니다.

### 6.5 폰 배포 상태에서 로컬로도 확인하기

백엔드에 키가 켜져 있으면 **로컬 프론트도 같은 키를 보내야** 합니다. `flutter run`에
키를 넘겨 같은(Docker) 백엔드에 붙이세요.

```bash
cd app
flutter run -d chrome \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=WS_BASE_URL=ws://localhost:8000 \
  --dart-define=API_KEY=<BACKEND_API_KEY 와 동일>
```

폰(`https://<host>.ts.net`)과 로컬(`http://localhost:8000`)이 **같은 백엔드 하나**를
동시에 봐도 됩니다. 단, 로컬 개발한다고 **uvicorn을 따로 또 띄우지 마세요** — 같은
`service.db`를 두 프로세스가 쓰면 SQLite 잠금이 납니다(§5.1). 백엔드는 Docker 것 하나만.

### 6.6 배포 vs 로컬 API 키 요약

| 상황 | `.env`의 `BACKEND_API_KEY` | 프론트에서 |
|---|---|---|
| 순수 로컬 개발 | 비움 | 아무 설정 불필요 |
| 폰 배포(외부 노출) | 설정 | 빌드/실행 시 `--dart-define=API_KEY=<같은 키>` |

### 6.7 K8s는? — docker-compose 권장

단일 노드·단일 사용자·SQLite 구조에는 **docker-compose로 충분**합니다(단일 replica,
`restart:` 로 크래시 복구). Kubernetes는 선언적 설정·셀프힐·수평확장이 강점이지만 n=1
에서는 대부분 적용되지 않고, macOS에선 Lima/VM 간접 레이어 + SQLite용 PV까지 필요해
운영 부담만 커집니다. 여러 서비스로 분리하거나 다중 노드로 갈 때 재검토하세요.

## 주요 API 요약

모든 REST 응답은 기본적으로 아래 envelope를 따릅니다.

```json
{"data": "...", "error": null}
```

자주 쓰는 엔드포인트:

```text
GET  /api/portfolio
GET  /api/portfolio?broker=KIS
GET  /api/portfolio?broker=TOSS
GET  /api/portfolio/{account_type}
POST /api/portfolio/orders
POST /api/portfolio/orders/sync
POST /api/settings/toss
POST /api/settings/toss/test
GET  /api/heatmap?market=KOSPI&group_by=sector
GET  /api/stocks/{code}
GET  /api/screener?universe=KOSPI200
GET  /api/quant/undervalued
GET  /api/system/status
GET  /api/system/data-quality
GET  /api/automation/status
POST /api/automation/kill-switch
POST /api/backtest/run
GET  /api/backtest/runs
GET  /api/backtest/runs/{run_id}         # 매매 내역 + 로직 기반 매매 사유 포함
GET  /api/proposals                       # 승인형 반자동 — 오늘의 주문 제안 목록
POST /api/proposals/{id}/approve          # 승인 → 안전 게이트 → 브로커 제출
POST /api/proposals/{id}/reject
POST /api/proposals/batches/{batch_id}/approve-all
GET  /api/settings
POST /api/settings/universe/kospi200/refresh
POST /api/settings/universe/kosdaq150/refresh
WS   /ws/quotes
```

## 디렉토리 구조

```text
backend/   FastAPI, KIS, LLM, Telegram, 스케줄러, 배포 스크립트
research/  데이터 수집, 팩터, 백테스트, 최적화, 노트북
shared/    도메인 모델, SQLAlchemy 모델, DB 세션
app/       Flutter 클라이언트
data/      로컬 DB, 토큰, 수동 유니버스, 캐시
```

## 마지막 한 줄

Q-Lab은 자동으로 돈을 벌어주는 상자가 아니라, 투자 아이디어를 데이터로 검증하고
기록으로 복기하게 해주는 개인 연구소입니다. 실전 자동매매는 반드시 모의투자와
작은 규모의 검증을 거친 뒤에만 켜세요.
