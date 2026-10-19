# 멀티 세션 협업 프로토콜 (Claude-a / Claude-b)

> 이 문서는 **규칙**만 담는다(공개 레포에 있어도 되는 내용).
> 실제 진행 상황·메시지·plan·report 는 비공개 공유 보드 **`.coord/`** 에만 둔다.

## 0. 왜 이렇게 하나

| 사실 | 결과 |
|------|------|
| Q-lab 레포는 **public** | plan/report/세션 메시지를 이 레포에 커밋하면 안 됨 |
| `.omc/` 는 gitignore + 맥미니 로컬에만 존재 | 클라우드 세션은 과거 plan/report 를 볼 수 없음 |
| 로컬 브랜치가 GitHub 에 푸시되지 않으면 | 클라우드 세션은 옛 `main` 코드로 작업하게 됨 (충돌·중복) |
| Claude-a / Claude-b 는 **서로 다른 계정** | 세션 간 직접 메시지 도구는 계정을 못 넘음 |

→ 모든 세션(로컬·클라우드·두 계정)이 공통으로 접근할 수 있는 건 **GitHub 뿐**이다.
그래서 공유 채널 = **비공개 레포 `q-lab-coord`** 를 Q-lab 안의 `.coord/` 로 clone 해서 쓴다
(Q-lab 에서는 `.coord/` 가 gitignore 되어 있어 공개 레포로 새지 않는다).

## 1. 세션 ID

| ID | 계정 | 환경 | 비고 |
|----|------|------|------|
| `A1` | Claude-a | 로컬(맥미니) | 데이터·백테스트·실계좌 연동 작업 |
| `A2` | Claude-a | 클라우드 | 코드·테스트·리뷰 (DB·`.env` 없음) |
| `A3` | Claude-a | (예정) | |
| `B1` | Claude-b | — | 1주간 휴식 → 진행 중 작업은 인계 |

- 새 세션은 시작할 때 사용자에게 받은 ID 를 쓴다. 모르면 **먼저 물어본다** (ID 없이 보드에 쓰지 않는다).
- 새 ID 는 계정 접두어(`A`/`B`) + 다음 번호. 끝난 세션의 ID 는 재사용하지 않는다.

## 2. `.coord/` 구조 (비공개 레포 `q-lab-coord`)

```
.coord/
├── README.md          이 프로토콜 요약 + 링크
├── BOARD.md           작업 보드 — 진행 중/대기/완료, 담당, 브랜치, 잠금 경로, 사용자 확인 필요
├── DECISIONS.md       사용자 결정 로그 (append-only, 모든 세션이 따름)
├── sessions/<ID>.md   세션 카드 — 본인만 수정
├── inbox/<ID>/        수신함 — 새 파일만 추가, 처리 후 inbox/<ID>/done/ 으로 이동
├── inbox/ALL/         전체 공지 (breaking change 등)
├── handoffs/          작업 인계서
├── plan/              계획 (CLAUDE.md 규칙 1)
└── reports/           리포트 (CLAUDE.md 규칙 2)
```

`.omc/` 는 oh-my-claudecode 런타임 상태(머신 로컬)로 그대로 두고, **공유가 필요한 plan/report 는 `.coord/` 에 쓴다.**

헬퍼: `scripts/coord.sh`

```bash
scripts/coord.sh init                 # .coord/ clone (없으면) 또는 pull. 빈 레포면 골격 생성
scripts/coord.sh sync A2 "메시지"      # pull --rebase → commit → push (재시도 포함)
scripts/coord.sh status A2            # 진행 중 작업 + 내 수신함 + 최근 공지
scripts/coord.sh send A2 A1 slug      # 메시지 파일 생성(템플릿) → 경로 출력 → 본문 작성 후 sync
scripts/coord.sh done A2 <파일>        # 처리한 메시지를 done/ 으로 이동
```

## 3. 세션 시작 체크리스트 (작업 전에 반드시)

1. 내 세션 ID 확인 (모르면 사용자에게 질문).
2. `scripts/coord.sh init` — 실패하면 사용자에게 알리고(레포 미연결 등), 공유 보드 없이 진행한다는 사실을 리포트에 남긴다.
3. 읽기: `BOARD.md` → `DECISIONS.md`(최근분) → `sessions/<내ID>.md` → `inbox/<내ID>/` → `inbox/ALL/`(카드의 `last_seen_all` 이후).
4. 코드 기준선 확인: `git fetch` 후 **통합 브랜치**(BOARD 상단에 명시) 최신 위에 있는지 확인. 아니면 작업 전에 맞춘다.
5. 내 카드 갱신(`status: active`, 브랜치, 시작 시각) → `scripts/coord.sh sync <ID> "start"`.

## 4. 작업 규칙

### 4.1 작업 클레임 (중복 작업 방지)
- 작업을 시작하기 **전에** `BOARD.md` 에 행을 추가/클레임하고 바로 sync 한다.
  `| T-번호 | 작업 | 담당 | 브랜치 | 잠금 경로 | 상태 |`
- **잠금 경로**: 그 작업이 수정할 디렉터리/파일 glob. 다른 세션이 잠근 경로는 수정하지 않는다.
  꼭 필요하면 담당 세션에 메시지 + 사용자 확인.
- 아래 **공용 핫스팟**은 수정 전에 반드시 잠금을 건다 (한 번에 한 세션만):
  - `shared/db/models.py`, `shared/db/migrations/**` — Alembic revision 체인 충돌. 머지 시 `down_revision` 재연결 필수
  - `pyproject.toml`, `app/pubspec.yaml` — 의존성
  - `backend/app/main.py`(라우터·스케줄러 등록), `app/lib/core/routes.dart`
  - `CLAUDE.md`, `docs/collab/**`

### 4.2 브랜치·작업 디렉터리
- **1 세션 = 1 브랜치 = 1 작업 디렉터리.** 같은 체크아웃을 두 세션이 동시에 쓰지 않는다.
  - 로컬(맥미니)에서 세션을 여러 개 띄울 때: `git worktree add ../Q-lab-<ID> -b <id>/<slug> <통합브랜치>`
  - `.coord/` 는 worktree 마다 따로 clone 한다 (`scripts/coord.sh init`).
- 브랜치 이름: `<id>/<slug>` (예: `a1/dc-irp-rebalance`). 클라우드 세션은 하네스가 정한 `claude/...` 이름을 쓰고, 카드에 기록한다.
- 통합: 작업 브랜치 → (draft PR) → 통합 브랜치. **머지는 사용자 승인 후.**
- 공개 레포 주의: `research/strategies/private/`, `.env*`, DB, 토큰은 절대 커밋하지 않는다 (기존 `.gitignore` 유지).

### 4.3 메시지 (세션 → 세션)
- 수신자 폴더에 **새 파일**로 쓴다: `inbox/<받는ID>/<YYYYMMDD-HHMM>_<보낸ID>_<slug>.md` (템플릿: `docs/collab/templates/message.md`).
- `type`: `info` | `request` | `question` | `handoff` | `breaking`
- **breaking change** (API 스키마, DB 스키마, `shared/domain`, 공용 유틸 시그니처 변경) → `inbox/ALL/` 에 공지 필수.
- 수신자는 처리 후 `scripts/coord.sh done` 으로 `done/` 이동. 답장은 상대 수신함에 새 파일로.
- 급하면 사용자에게 "A1 에게 inbox 확인 요청" 이라고 전달을 부탁한다
  (같은 계정 클라우드 세션끼리는 원격 세션 메시지 도구로 알림만 보낼 수 있다. 내용의 정본은 항상 `.coord/`).

### 4.4 사용자 결정
- 사용자가 내린 결정은 `DECISIONS.md` 에 한 줄씩 추가: `- 2026-10-19 [A2] 결정 내용 (근거/맥락)`.
- 여러 세션이 같은 질문을 반복하지 않도록, 질문 전에 `DECISIONS.md` 와 BOARD 의 **사용자 확인 필요** 섹션을 먼저 본다.
- 사용자에게 물을 게 생기면 BOARD 의 **사용자 확인 필요** 에도 적는다 (사용자가 한 곳에서 모아 볼 수 있게).

### 4.5 커밋 (CLAUDE.md 규칙 3 그대로)
- 검증 통과 시에만, 작업 단위 원자적 커밋, 한국어 한 줄 요약.
- `.coord/` 커밋 메시지는 `<ID>: <요약>` (예: `A2: T-003 클레임`).

## 5. 작업 완료 / 세션 종료

**작업 완료 시**
1. `.coord/reports/<날짜>_<slug>.md` 리포트 작성 (작성 세션 ID 명시).
2. BOARD 행 → `완료` + 커밋 해시/PR 링크.
3. 영향받는 세션에 메시지 (breaking 이면 `inbox/ALL/`).

**세션 종료·장기 중단 시** (B1 처럼 며칠 이상 못 할 때 특히)
1. 코드: 커밋 가능한 건 커밋·푸시. 미완성 변경은 WIP 브랜치로 푸시하거나 카드에 "미커밋 변경 있음" 명시.
2. 카드: `status: paused|ended`, **다음 할 일**, 블로커, 마지막 커밋.
3. 다른 세션이 이어받아야 하면 `handoffs/<날짜>_<from>-to-<to>_<slug>.md` (템플릿: `templates/handoff.md`) + 받는 세션 수신함에 `type: handoff` 메시지.
4. `scripts/coord.sh sync <ID> "pause"`.

## 6. `.coord/` 충돌 방지

- **세션 카드는 본인만**, **수신함은 새 파일만** → 이 둘은 충돌이 나지 않는다.
- `BOARD.md`·`DECISIONS.md` 는 수정 직전 pull, 행 단위로 작게 수정, 즉시 push (`coord.sh sync` 가 처리).
- push 충돌 시 다시 pull --rebase 후 재적용. **force-push 금지.**

## 7. 안전 규칙 (모든 세션 공통, CLAUDE.md 4-1·5 재확인)

- KIS 계좌 검증 순서 PAPER → REAL → ISA 불변. REAL 자동 주문은 승인형 반자동만.
- 클라우드 세션은 실계좌·실데이터로 검증할 수 없다 → 주문/브로커 경로를 바꾸면 리포트와 BOARD 에
  **"로컬 실검증 필요"** 를 표시하고 A1(로컬)에 검증 요청 메시지를 보낸다.
- `app_secret`, API 키, 텔레그램 토큰은 `.coord/` 에도 쓰지 않는다 (비공개 레포라도 금지).
