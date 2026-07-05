# Q-Lab — Claude 작업 정책

## 프로젝트 개요
KIS + Toss 기반 개인 주식 앱. FastAPI(backend) + Flutter(app) + Python 퀀트 파이프라인(research).
전체 구조는 [AGENTS.md](AGENTS.md) 참고.

---

## 작업 진행 규칙 (모든 세션 적용)

### 1. 계획 → `.omc/plan/`
- 새 기능·버그픽스 설계 전, 계획 파일을 `.omc/plan/<YYYY-MM-DD>_<slug>.md` 에 먼저 작성한다.
- 계획 파일 구조: 목표 / 탐색 결과 / 설계 결정 / 작업 단계 / 검증 기준.
- 사용자 승인 후 구현을 시작한다.

### 2. 작업 리포트 → `.omc/reports/`
- 작업 단위(기능, 버그픽스, 문서화 등)가 완료되면 `.omc/reports/<YYYY-MM-DD>_<slug>.md` 에 리포트를 작성한다.
- 리포트 구조: 작업 내용 / 변경 파일 / 검증 결과 / 이슈 & 미결.

### 3. Git 커밋 — 검증 통과 시에만
- **커밋 조건**: 해당 작업의 검증(테스트, analyze, 수동 확인)이 모두 통과한 경우에만 커밋.
- **커밋 단위**: 작업(task) 단위로 원자적 커밋. 여러 task를 한 커밋에 묶지 않는다.
- **커밋 메시지**: 한국어, 무엇을 했는지 한 줄 요약. 예: `deepinit: 전체 코드베이스 AGENTS.md 계층 문서화`
- Flutter 변경 시 검증: `flutter analyze && flutter test`
- Python 변경 시 검증: `pytest backend/tests/ -v` 또는 `pytest research/tests/ -v`

### 4. 코드 수정 경계 (절대 불변)
- `app/` Flutter 코드만 직접 수정.
- `backend/`, `research/`, `shared/` Python 코드는 **절대 수정 금지** (Codex 담당).
- 백엔드 필요 변경사항은 `.omc/plan/` 의 "Codex 요청" 섹션에 명시.

### 5. 보안 규칙
- `app_secret`, API 키, Telegram 토큰을 절대 로그에 남기지 않는다.
- KIS 계좌 검증 순서: PAPER(모의) → REAL → ISA (절대 변경 금지).

---

## 디렉터리 용도 요약

| 경로 | 용도 |
|------|------|
| `.omc/plan/` | 기능·버그 설계 계획 파일 |
| `.omc/reports/` | 완료된 작업별 리포트 |
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
