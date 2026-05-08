"""DRF-358 T02: food clarification keyboard + 2 callback handlers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from maxapi.context.context import MemoryContext


def _flatten(keyboard) -> set[str]:
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


def test_keyboard_has_two_buttons():
    from maxbot.keyboards import (
        food_drink_clarify_keyboard,
        PAYLOAD_FOOD_TO_DIARY,
        PAYLOAD_FOOD_TYPO,
    )
    keyboard = food_drink_clarify_keyboard()
    payloads = _flatten(keyboard)
    assert PAYLOAD_FOOD_TO_DIARY in payloads
    assert PAYLOAD_FOOD_TYPO in payloads


def _fake_callback(payload: str) -> MagicMock:
    cb = MagicMock()
    cb.callback.payload = payload
    cb.callback.user = MagicMock(user_id=200, full_name="Аня")
    cb.message.recipient.chat_id = 100
    cb.bot = MagicMock()
    cb.bot.send_message = AsyncMock()
    return cb


@pytest.mark.asyncio
async def test_on_food_to_diary_redirects_to_photo(monkeypatch):
    """[📝 В дневник] click → bot prompts photo (text food log не реализован)."""
    from maxbot.handlers.food_clarify import on_food_to_diary
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_clarify.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:ux:food_to_diary")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_food_to_diary(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs.get("text") or ""
    assert "фото" in text.lower() or "📸" in text


@pytest.mark.asyncio
async def test_on_food_typo_silent_ack(monkeypatch):
    """[Опечатка] click → silent ack, минимальная reaction."""
    from maxbot.handlers.food_clarify import on_food_typo
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_clarify.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:ux:food_typo")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_food_typo(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs.get("text") or ""
    # Soft / minimal — короткий ack, без длинной mansplain
    assert len(text) < 100
