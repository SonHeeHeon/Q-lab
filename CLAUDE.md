# Q-Lab — Claude 작업 정책

## 프로젝트 개요
KIS + Toss 기반 개인 주식 앱. FastAPI(backend) + Flutter(app) + Python 퀀트 파이프라인(research).
전체 구조는 [AGENTS.md](AGENTS.md) 참고.

---

## 작업 진행 규칙 (모든 세션 적용)

### 1. 계획 → `.coord/plan/` (없으면 `.omc/plan/`)
- 새 기능·버그픽스 설계 전, 계획 파일을 `.coord/plan/<YYYY-MM-DD>_<slug>.md` 에 먼저 작성한다.
  `.coord/`(공유 보드)를 쓸 수 없는 경우에만 `.omc/plan/` 에 쓰고, 나중에 `.coord/` 로 옮긴다.
- 계획 파일 구조: 목표 / 탐색 결과 / 설계 결정 / 작업 단계 / 검증 기준.
- 사용자 승인 후 구현을 시작한다.

### 2. 작업 리포트 → `.coord/reports/` (없으면 `.omc/reports/`)
- 작업 단위(기능, 버그픽스, 문서화 등)가 완료되면 `.coord/reports/<YYYY-MM-DD>_<slug>.md` 에 리포트를 작성한다 (작성 세션 ID 명시).
- 리포트 구조: 작업 내용 / 변경 파일 / 검증 결과 / 이슈 & 미결.

### 3. Git 커밋 — 검증 통과 시에만
- **커밋 조건**: 해당 작업의 검증(테스트, analyze, 수동 확인)이 모두 통과한 경우에만 커밋.
- **커밋 단위**: 작업(task) 단위로 원자적 커밋. 여러 task를 한 커밋에 묶지 않는다.
- **커밋 메시지**: 한국어, 무엇을 했는지 한 줄 요약. 예: `deepinit: 전체 코드베이스 AGENTS.md 계층 문서화`
- Flutter 변경 시 검증: `flutter analyze && flutter test`
- Python 변경 시 검증: `pytest backend/tests/ -v` 또는 `pytest research/tests/ -v`

### 4. 코드 수정 범위 — 풀스택 (2026-07-06 업데이트)
- Claude가 **`app/`(Flutter) + `backend/`·`research/`·`shared/`(Python) 전체**를 직접 구현·수정한다.
- (기존 "backend/research/shared는 Codex 담당, 수정 금지" 분리 규칙은 사용자 지시로 **폐지**됨.)
- Python 변경 시 반드시 관련 테스트(`pytest`) 통과를 검증한 뒤 커밋한다.

### 4-1. 여전히 불변인 안전 규칙
- KIS 계좌 검증 순서: PAPER(모의) → REAL → ISA (절대 변경 금지).
- 실전(REAL) 계좌로 나가는 자동 주문은 승인형 반자동만 허용 (제안 → 사용자 승인 → 실행).

### 5. 보안 규칙
- `app_secret`, API 키, Telegram 토큰을 절대 로그에 남기지 않는다.
- KIS 계좌 검증 순서: PAPER(모의) → REAL → ISA (절대 변경 금지).

### 6. 멀티 세션 협업 (Claude-a / Claude-b, 2026-10-19 신설)
- 전체 규칙: [docs/collab/PROTOCOL.md](docs/collab/PROTOCOL.md). 이 레포는 **public** 이므로 진행 상황·메시지·plan·report 는
  비공개 레포 `q-lab-coord` 를 clone 한 **`.coord/`** 에만 쓴다 (gitignore 됨).
- **세션 시작 시 (작업 전 필수)**
  1. 내 세션 ID(A1/A2/A3/B1…) 확인 — 모르면 사용자에게 먼저 묻는다.
  2. `scripts/coord.sh init` → `BOARD.md` · `DECISIONS.md` · `sessions/<ID>.md` · `inbox/<ID>/` · `inbox/ALL/` 읽기.
  3. BOARD 의 **통합 브랜치** 최신 위에서 작업하는지 확인.
- **작업 전**: BOARD 에 클레임(담당·브랜치·잠금 경로) 후 `scripts/coord.sh sync <ID> "<요약>"`. 남이 잠근 경로는 수정 금지.
- **1 세션 = 1 브랜치 = 1 작업 디렉터리.** 로컬에서 여러 세션을 띄우면 `git worktree` 로 분리한다.
- **공용 핫스팟**(`shared/db/models.py`·`shared/db/migrations/**`·`pyproject.toml`·`app/pubspec.yaml`·`backend/app/main.py`·`app/lib/core/routes.dart`)은 잠금 필수.
- 다른 세션에 알릴 일 → `inbox/<ID>/` 에 새 파일 (`scripts/coord.sh send`). API·DB 스키마 변경은 `inbox/ALL/` 공지.
- 사용자 결정 → `DECISIONS.md` 에 한 줄 추가. 묻기 전에 먼저 확인한다.
- **세션 종료·중단 시**: 세션 카드에 다음 할 일·미커밋 변경 기록, 필요하면 `handoffs/` 인계서, sync.

---

## 디렉터리 용도 요약

| 경로 | 용도 |
|------|------|
| `.coord/` | 세션 간 공유 보드 (비공개 레포 `q-lab-coord` clone, gitignore) — BOARD·세션카드·inbox·plan·reports |
| `.omc/` | oh-my-claudecode 런타임 상태 (머신 로컬). `.coord/` 를 쓸 수 없을 때만 plan/reports 임시 보관 |
| `docs/collab/` | 멀티 세션 협업 규칙 + 템플릿 (공개 가능 내용만) |
| `AGENTS.md` (계층) | AI 에이전트용 코드베이스 문서 (deepinit 생성) |
| `PROJECT_BLUEPRINT.md` | 전체 제품 기획 SSoT |

---

## 자주 쓰는 검증 명령

```bash
# Flutter
cd app && flutter analyze
cd app && flutter test

# Backend
pytest backend/tests/ -v

# Research
pytest research/tests/ -v

# 전체 AGENTS.md 목록 확인
find . -name "AGENTS.md" -not -path "*/__pycache__/*" | sort
```
