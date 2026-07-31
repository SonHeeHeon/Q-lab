"""텔레그램 승인 트랙 — long polling 콜백 수신 + 2단계 확인 처리.

앱 트랙과 같은 DB·같은 승인 서비스(approval.approve_and_execute)를 쓰므로
어느 쪽에서 처리해도 다른 쪽은 원자적 CAS 덕에 "이미 처리됨"이 된다.

안전장치:
- chat_id 화이트리스트: 설정된 TELEGRAM_CHAT_ID 외의 콜백은 무시(내용 미로깅).
- 2단계 확인: [승인]/[모두 승인/거절] 탭 → 키보드가 "⚠️ 한 번 더" 확인
  버튼으로 바뀌고, 재탭해야 실행. 건별 거절만 원탭.
- 실행은 기존 안전게이트·멱등·라이브잠금·연금차단 전부 그대로 통과.
"""
from __future__ import annotations

import asyncio
import logging

from backend.app.services.notify.telegram import TelegramClient, TelegramSendError

logger = logging.getLogger(__name__)

# callback_data 액션들. cf:* = 확인 단계를 거친 실제 실행.
_ACTIONS = {"ap", "rj", "apall", "rjall", "back"}
_CONFIRM_ACTIONS = {"cf:ap", "cf:apall", "cf:rjall"}


def parse_callback(data: str) -> tuple[str, str] | None:
    """callback_data → (action, target). 알 수 없는 형식은 None.

    형식: `ap:{id}` `rj:{id}` `apall:{batch}` `rjall:{batch}` `back:{batch}`
    `cf:ap:{id}` `cf:apall:{batch}` `cf:rjall:{batch}`
    """
    if not data or len(data) > 64:
        return None
    parts = data.split(":")
    if len(parts) == 2 and parts[0] in _ACTIONS and parts[1]:
        return parts[0], parts[1]
    if (
        len(parts) == 3
        and parts[0] == "cf"
        and f"cf:{parts[1]}" in _CONFIRM_ACTIONS
        and parts[2]
    ):
        return f"cf:{parts[1]}", parts[2]
    return None


def confirm_markup(action: str, target: str, batch_id: str | None) -> dict:
    """1차 탭 후 보여줄 확인 키보드 — 재탭 시 실행, 취소 시 원 키보드 복원."""
    label = {
        "ap": "⚠️ 승인 실행 — 한 번 더",
        "apall": "⚠️ 전체 승인 실행 — 한 번 더",
        "rjall": "⚠️ 전체 거절 — 한 번 더",
    }[action]
    rows = [[{"text": label, "callback_data": f"cf:{action}:{target}"}]]
    if batch_id:
        rows.append([{"text": "↩️ 취소", "callback_data": f"back:{batch_id}"}])
    return {"inline_keyboard": rows}


def is_whitelisted(update: dict, chat_id: str) -> bool:
    """콜백의 chat과 **누른 사람(from.id)** 둘 다 설정 chat_id와 일치해야 통과.

    개인 챗에선 둘이 같아 무해하고, 그룹 챗으로 옮기면 그룹원 전원이 주문을
    승인하게 되는 구멍을 from.id 검사가 막는다 (2026-08-01 리뷰 P2-7).
    """
    cb = update.get("callback_query") or {}
    chat = str(((cb.get("message") or {}).get("chat") or {}).get("id", ""))
    sender = str((cb.get("from") or {}).get("id", ""))
    return bool(chat_id) and chat == str(chat_id) and sender == str(chat_id)


class TelegramCommandRunner:
    """getUpdates long polling 루프 — 서버 상시 기동 시 백그라운드 태스크."""

    def __init__(self, client: TelegramClient | None = None) -> None:
        self._client = client or TelegramClient()
        self._offset = 0

    async def run_forever(self) -> None:
        if not self._client.bot_token or not self._client.chat_id:
            logger.info("telegram command runner disabled (no credentials)")
            return
        logger.info("telegram command runner started (long polling)")
        backoff = 1
        while True:
            try:
                updates = await self._client.get_updates(self._offset)
                backoff = 1
                for update in updates:
                    self._offset = max(
                        self._offset, int(update.get("update_id", 0)) + 1
                    )
                    try:
                        await self.handle_update(update)
                    except Exception:  # noqa: BLE001 — 한 콜백 실패 격리
                        logger.exception("telegram callback handling failed")
            except asyncio.CancelledError:
                raise
            except TelegramSendError:
                logger.warning("telegram polling error — backoff %ss", backoff)
                await asyncio.sleep(backoff)
                backoff = min(60, backoff * 2)
            except Exception:  # noqa: BLE001 — 폴링 루프는 죽지 않는다
                logger.exception("telegram polling unexpected error")
                await asyncio.sleep(backoff)
                backoff = min(60, backoff * 2)

    async def handle_update(self, update: dict) -> None:
        cb = update.get("callback_query")
        if not cb:
            return
        cb_id = str(cb.get("id", ""))
        if not is_whitelisted(update, str(self._client.chat_id)):
            logger.warning("telegram callback from non-whitelisted chat ignored")
            return
        parsed = parse_callback(cb.get("data") or "")
        message = cb.get("message") or {}
        message_id = message.get("message_id")
        text = message.get("text") or ""
        if parsed is None or message_id is None:
            await self._client.answer_callback(cb_id, "알 수 없는 요청")
            return
        action, target = parsed

        from backend.app.services.batch.proposal_generator import proposal_keyboard

        if action in ("ap", "apall", "rjall"):
            # 1차 탭 → 확인 키보드로 교체 (2단계 확인)
            batch_id = target if action != "ap" else await self._batch_of(target)
            await self._client.edit_message(
                message_id, text,
                reply_markup=confirm_markup(action, target, batch_id),
            )
            await self._client.answer_callback(cb_id, "한 번 더 누르면 실행됩니다")
            return

        if action == "back":
            await self._client.edit_message(
                message_id, text, reply_markup=await proposal_keyboard(target)
            )
            await self._client.answer_callback(cb_id, "취소됨")
            return

        if action == "rj":
            note = await self._reject(int(target))
            batch_id = await self._batch_of(target)
            await self._finish(
                cb_id, message_id, text, note,
                batch_id=batch_id,
            )
            return

        if action == "cf:ap":
            note = await self._approve(int(target))
            batch_id = await self._batch_of(target)
            await self._finish(cb_id, message_id, text, note, batch_id=batch_id)
            return

        if action in ("cf:apall", "cf:rjall"):
            notes = await self._bulk(target, approve=(action == "cf:apall"))
            await self._finish(
                cb_id, message_id, text, " / ".join(notes) or "처리할 제안 없음",
                batch_id=target,
            )

    # --- 실행 헬퍼 (세션·클라이언트 자체 생성) --------------------------------

    async def _approve(self, proposal_id: int) -> str:
        from backend.app.api.portfolio import _schedule_order_tracking
        from backend.app.services.kis.rest_client import KISRestClient
        from backend.app.services.orders.approval import approve_and_execute
        from shared.db.session import service_session

        async with service_session() as session:
            outcome = await approve_and_execute(
                proposal_id, session=session, kis_client=KISRestClient()
            )
        if outcome.should_track and outcome.trade_id:
            asyncio.create_task(_schedule_order_tracking(outcome.trade_id))
        prefix = {
            "submitted": "✅ 제출됨",
            "replayed": "✅ 제출됨(멱등)",
            "blocked": "⛔ 차단",
            "failed": "❌ 실패",
            "conflict": "이미 처리됨",
            "not_found": "없음",
        }.get(outcome.status, outcome.status)
        detail = f" — {outcome.note}" if outcome.note else ""
        return f"{prefix} #{proposal_id}{detail}"

    async def _reject(self, proposal_id: int) -> str:
        from backend.app.services.orders.approval import reject_proposal_cas
        from shared.db.session import service_session

        async with service_session() as session:
            row = await reject_proposal_cas(proposal_id, session=session)
        return (
            f"❌ 거절됨 #{proposal_id}" if row is not None
            else f"이미 처리됨 #{proposal_id}"
        )

    async def _bulk(self, batch_id: str, *, approve: bool) -> list[str]:
        from sqlalchemy import select

        from shared.db.models import OrderProposal
        from shared.db.session import service_session

        async with service_session() as session:
            ids = [
                row[0]
                for row in (
                    await session.execute(
                        select(OrderProposal.id)
                        .where(OrderProposal.batch_id == batch_id)
                        .where(OrderProposal.status == "PROPOSED")
                        .order_by(OrderProposal.id)
                    )
                ).all()
            ]
        notes = []
        for pid in ids:
            notes.append(
                await (self._approve(pid) if approve else self._reject(pid))
            )
        return notes

    async def _batch_of(self, proposal_id: str) -> str | None:
        from sqlalchemy import select

        from shared.db.models import OrderProposal
        from shared.db.session import service_session

        try:
            pid = int(proposal_id)
        except ValueError:
            return None
        async with service_session() as session:
            row = (
                await session.execute(
                    select(OrderProposal.batch_id).where(OrderProposal.id == pid)
                )
            ).first()
        return row[0] if row else None

    async def _finish(
        self,
        cb_id: str,
        message_id: int,
        text: str,
        note: str,
        *,
        batch_id: str | None,
    ) -> None:
        """결과를 메시지에 덧붙이고 남은 제안으로 키보드 재구성."""
        from backend.app.services.batch.proposal_generator import proposal_keyboard

        markup = await proposal_keyboard(batch_id) if batch_id else None
        new_text = f"{text}\n{note}"[:4000]
        try:
            await self._client.edit_message(
                message_id, new_text, reply_markup=markup
            )
        except TelegramSendError:
            logger.warning("telegram edit_message failed (result: %s)", note)
        await self._client.answer_callback(cb_id, note[:180])
