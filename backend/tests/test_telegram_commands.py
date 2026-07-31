"""텔레그램 승인 트랙 — 콜백 파싱·화이트리스트·2단계 확인 전이."""
from __future__ import annotations

from backend.app.services.notify.telegram_commands import (
    confirm_markup,
    is_whitelisted,
    parse_callback,
)


def test_parse_callback_actions():
    assert parse_callback("ap:123") == ("ap", "123")
    assert parse_callback("rj:9") == ("rj", "9")
    assert parse_callback("apall:abcd1234") == ("apall", "abcd1234")
    assert parse_callback("cf:ap:123") == ("cf:ap", "123")
    assert parse_callback("cf:rjall:abcd") == ("cf:rjall", "abcd")
    assert parse_callback("back:abcd") == ("back", "abcd")


def test_parse_callback_rejects_garbage():
    assert parse_callback("") is None
    assert parse_callback("nuke:1") is None
    assert parse_callback("cf:rj:1") is None  # 건별 거절은 확인 단계 없음
    assert parse_callback("ap:") is None
    assert parse_callback("x" * 100) is None


def test_confirm_markup_two_step():
    markup = confirm_markup("ap", "123", "batch1")
    rows = markup["inline_keyboard"]
    assert rows[0][0]["callback_data"] == "cf:ap:123"  # 재탭 시 실행
    assert rows[1][0]["callback_data"] == "back:batch1"  # 취소 → 원 키보드


def test_is_whitelisted():
    update = {"callback_query": {"message": {"chat": {"id": 777}}}}
    assert is_whitelisted(update, "777") is True
    assert is_whitelisted(update, "888") is False
    assert is_whitelisted(update, "") is False
    assert is_whitelisted({}, "777") is False
