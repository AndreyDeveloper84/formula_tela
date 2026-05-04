"""Phase 3.1 Part 2A T07-T11: scan correction router."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from maxapi.context.context import MemoryContext


pytestmark = pytest.mark.django_db


def _fake_callback(payload, chat_id=100, user_id=200):
    cb = MagicMock()
    cb.callback.payload = payload
    cb.callback.user = MagicMock(user_id=user_id, full_name="Тест")
    cb.message.recipient.chat_id = chat_id
    cb.bot.send_message = AsyncMock()
    return cb


def _flatten_payloads(keyboard):
    out = set()
    rows = (
        getattr(getattr(keyboard, "payload", None), "buttons", None)
        or getattr(keyboard, "buttons", None)
        or getattr(keyboard, "rows", None)
        or []
    )
    for row in rows:
        for btn in row:
            payload = getattr(btn, "payload", None)
            if payload is None:
                callback = getattr(btn, "callback", None)
                payload = getattr(callback, "payload", None) if callback else None
            if payload:
                out.add(payload)
    return out


@pytest.mark.asyncio
async def test_correct_open_menu_shows_4_options():
    """Клик «✏️ Поправить» (cb:scan:correct:menu:{scan_id}) → открыть menu."""
    from maxbot.handlers.food_correction import on_correct_open_menu

    cb = _fake_callback("cb:scan:correct:menu:S1")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_correct_open_menu(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    # Текст «Что не так?» по Design §5.4
    assert "не так" in text.lower() or "Что" in text
    # Attachments — keyboard с 4 опциями
    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    assert atts
