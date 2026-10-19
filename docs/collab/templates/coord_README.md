# q-lab-coord — Q-Lab 세션 간 공유 보드 (비공개)

Q-lab(공개) 레포의 `.coord/` 에 clone 해서 쓴다. 규칙 전문은 Q-lab 레포의 `docs/collab/PROTOCOL.md`.

## 세션 시작할 때
1. 내 세션 ID 확인 (A1/A2/A3/B1…) — 모르면 사용자에게 질문
2. `scripts/coord.sh init`
3. BOARD.md → DECISIONS.md → sessions/<ID>.md → inbox/<ID>/ → inbox/ALL/ 순서로 읽기
4. 카드 갱신 후 `scripts/coord.sh sync <ID> "start"`

## 작업할 때
- 시작 전 BOARD 에 클레임(담당·브랜치·잠금 경로) → sync
- 다른 세션에 알릴 일 → `scripts/coord.sh send <나> <상대> <slug>`
- 사용자 결정 → DECISIONS.md

## 끝낼 때
- reports/ 에 리포트, BOARD 완료 처리, 카드에 "다음 할 일", 필요하면 handoffs/
- `scripts/coord.sh sync <ID> "pause"`

**비밀값(API 키·토큰·계좌번호 전체)은 여기에도 쓰지 않는다.**
