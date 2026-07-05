# 작업 리포트 — deepinit: 전체 AGENTS.md 계층 문서화

**날짜**: 2026-07-06  
**작업 유형**: 문서화 (deepinit)  
**작업자**: Claude (Sonnet 4.6)

---

## 작업 내용

`/deepinit` 스킬을 사용하여 전체 코드베이스에 AI 에이전트용 계층형 AGENTS.md 문서를 생성.  
각 파일은 `<!-- Parent: ../AGENTS.md -->` 태그로 계층 탐색이 가능하며,  
AI가 해당 디렉터리에서 작업할 때 알아야 할 핵심 규칙과 파일 목록을 포함.

## 생성된 파일 (49개)

| Level | 범위 | 파일 수 |
|-------|------|---------|
| 0 — Root | `/AGENTS.md` | 1 |
| 1 — Packages | `app/`, `backend/`, `research/`, `shared/` | 4 |
| 2 — Subpackages | `app/lib/`, `app/test/`, `backend/app/`, `backend/tests/`, `shared/db/domain/utils/`, research 6 모듈 | 13 |
| 3 — Layers | `core/`, `data/`, `domain/`, `presentation/`, `api/`, `services/`, `schemas/`, `ws/` | 10 |
| 4 — Features | 12 presentation 화면 + 8 backend service + `data/api/`, `data/ws/`, `entities/` | 21 |
| **합계** | | **49** |

## 주요 문서화 내용

- **브로커 라우팅**: KR→KIS, US→TOSS 분기 규칙 명시 (presentation/stocks, portfolio)
- **KIS 계좌 검증 순서**: PAPER → REAL → ISA (절대 불변) — `kis/AGENTS.md`, `entities/AGENTS.md`
- **백엔드 수정 금지 경계**: `app/`만 직접 수정 — 루트 AGENTS.md
- **safeDouble 파싱 규칙**: Decimal→String 변환 처리 — `data/api/AGENTS.md`
- **백테스트 5-output 형식 + walk-forward 필수** — `research/backtest/AGENTS.md`
- **보안**: 비밀키 로깅 금지 규칙 — `kis/`, `toss/`, `llm/`, `notify/` AGENTS.md
- **Toss 예수금 버그 메모**: `_cash_money_dict` 키 누락 (Codex R2 미결) — `toss/AGENTS.md`

## 검증 결과

```
find . -name "AGENTS.md" | wc -l → 49 ✅
parent 태그 존재 여부 → 루트 제외 전체 포함 ✅
고아 파일 없음 ✅
```

## 이슈 & 미결

- `app/lib/presentation/quant/backtest_lab/`, `builder/`, `insights_tab/` 하위 Level 5는 생략 (파일 수 적음)
- `research/notebooks/`, `research/scripts/`, `research/tests/` AGENTS.md 생략 (보조 디렉터리)
- Toss `_cash_money_dict` 버그 — Codex R2 요청 대기 중
