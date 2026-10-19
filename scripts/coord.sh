#!/usr/bin/env bash
# =============================================================================
# 세션 간 공유 보드(.coord/ = 비공개 레포 q-lab-coord) 동기화 헬퍼.
# 규칙: docs/collab/PROTOCOL.md
#
#   scripts/coord.sh init                    clone(없으면) 또는 pull. 빈 레포면 골격 생성
#   scripts/coord.sh sync <ID> "<메시지>"     pull --rebase → commit → push
#   scripts/coord.sh status <ID>             진행 중 작업 + 내 수신함 + 최근 공지
#   scripts/coord.sh send <FROM> <TO> <slug> 메시지 파일 생성 후 경로 출력 (TO=ALL 은 공지)
#   scripts/coord.sh done <ID> <파일>         처리한 메시지를 inbox/<ID>/done/ 으로 이동
#
# 환경변수: COORD_DIR(기본 <repo>/.coord), COORD_REMOTE(기본 SonHeeHeon/q-lab-coord)
# =============================================================================
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
COORD_DIR="${COORD_DIR:-$ROOT/.coord}"
COORD_REMOTE="${COORD_REMOTE:-https://github.com/SonHeeHeon/q-lab-coord.git}"
TEMPLATES="$ROOT/docs/collab/templates"
SESSION_IDS=(A1 A2 A3 B1)

die() { echo "[coord] $*" >&2; exit 1; }

# 네트워크 오류 대비 지수 백오프 재시도 (2s, 4s, 8s, 16s)
retry() {
  local delay=2
  for _ in 1 2 3 4; do
    "$@" && return 0
    echo "[coord] 재시도 ${delay}s 후: $*" >&2
    sleep "$delay"
    delay=$((delay * 2))
  done
  "$@"
}

g() { git -C "$COORD_DIR" "$@"; }

require_repo() {
  [ -d "$COORD_DIR/.git" ] || die ".coord/ 없음 — 먼저 'scripts/coord.sh init'"
}

require_id() {
  [[ "${1:-}" =~ ^[AB][0-9]+$ ]] || die "세션 ID 형식 오류: '${1:-}' (예: A2)"
}

seed() {
  echo "[coord] 빈 레포 — 템플릿으로 골격 생성"
  cp "$TEMPLATES/coord_README.md" "$COORD_DIR/README.md"
  cp "$TEMPLATES/BOARD.md" "$TEMPLATES/DECISIONS.md" "$COORD_DIR/"
  mkdir -p "$COORD_DIR"/{sessions,handoffs,plan,reports,inbox/ALL}
  local id
  for id in "${SESSION_IDS[@]}"; do
    mkdir -p "$COORD_DIR/inbox/$id/done"
    touch "$COORD_DIR/inbox/$id/done/.gitkeep"
    sed "s/<ID>/$id/" "$TEMPLATES/session_card.md" > "$COORD_DIR/sessions/$id.md"
  done
  touch "$COORD_DIR"/{handoffs,plan,reports,inbox/ALL}/.gitkeep
  g add -A
  g commit -qm "골격 생성 (docs/collab/templates)"
  retry g push -q -u origin HEAD:main
}

cmd_init() {
  if [ -d "$COORD_DIR/.git" ]; then
    retry g pull -q --rebase --autostash
    echo "[coord] pull 완료: $COORD_DIR"
    return
  fi
  retry git clone -q "$COORD_REMOTE" "$COORD_DIR" \
    || die "clone 실패 — 레포가 없거나 이 세션에 연결되지 않음 ($COORD_REMOTE)"
  if [ -z "$(g ls-files)" ]; then seed; fi
  echo "[coord] 준비 완료: $COORD_DIR"
}

cmd_sync() {
  require_repo
  require_id "${1:-}"
  local id="$1" msg="${2:-update}"
  g add -A
  if ! g diff --cached --quiet; then
    g commit -qm "$id: $msg"
  fi
  retry g pull -q --rebase --autostash
  retry g push -q
  echo "[coord] sync 완료 ($id: $msg)"
}

cmd_status() {
  require_repo
  require_id "${1:-}"
  local id="$1"
  echo "== 진행 중 (BOARD.md) =="
  awk '/^## .*진행 중/{f=1;next} /^## /{f=0} f && /^\| *T-/' "$COORD_DIR/BOARD.md" || true
  echo
  echo "== 사용자 확인 필요 =="
  awk '/^## .*사용자 확인 필요/{f=1;next} /^## /{f=0} f && /^\| *[0-9]/' "$COORD_DIR/BOARD.md" || true
  echo
  echo "== inbox/$id (미처리) =="
  find "$COORD_DIR/inbox/$id" -maxdepth 1 -name '*.md' 2>/dev/null | sort | sed "s|$COORD_DIR/||"
  echo
  echo "== inbox/ALL (최근 5건) =="
  find "$COORD_DIR/inbox/ALL" -maxdepth 1 -name '*.md' 2>/dev/null | sort | tail -5 | sed "s|$COORD_DIR/||"
}

cmd_send() {
  require_repo
  require_id "${1:-}"
  local from="$1" to="${2:-}" slug="${3:-}"
  [ "$to" = "ALL" ] || require_id "$to"
  [ -n "$slug" ] || die "slug 필요"
  local now file
  now="$(date '+%Y%m%d-%H%M')"
  mkdir -p "$COORD_DIR/inbox/$to"
  file="$COORD_DIR/inbox/$to/${now}_${from}_${slug}.md"
  sed -e "s/<보낸ID>/$from/" \
      -e "s/<받는ID | ALL>/$to/" \
      -e "s/YYYY-MM-DD HH:MM/$(date '+%Y-%m-%d %H:%M')/" \
      "$TEMPLATES/message.md" > "$file"
  echo "$file"
}

cmd_done() {
  require_repo
  require_id "${1:-}"
  local id="$1" file="${2:-}"
  [ -n "$file" ] || die "파일 경로 필요"
  [ -f "$file" ] || file="$COORD_DIR/inbox/$id/$(basename "$file")"
  [ -f "$file" ] || die "메시지 없음: $2"
  mkdir -p "$COORD_DIR/inbox/$id/done"
  g mv "$file" "$COORD_DIR/inbox/$id/done/"
  echo "[coord] 처리 완료: $(basename "$file")"
}

case "${1:-}" in
  init)   shift; cmd_init "$@" ;;
  sync)   shift; cmd_sync "$@" ;;
  status) shift; cmd_status "$@" ;;
  send)   shift; cmd_send "$@" ;;
  done)   shift; cmd_done "$@" ;;
  *) sed -n '2,14p' "$0"; exit 1 ;;
esac
