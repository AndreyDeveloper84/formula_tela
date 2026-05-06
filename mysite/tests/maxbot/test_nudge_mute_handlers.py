"""Phase 3.2B T09: mute UI keyboards + handlers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import sync_to_async
from maxapi.context.context import MemoryContext
from model_bakery import baker

from services_app.models import BotUser, NudgeMute


pytestmark = pytest.mark.django_db(transaction=True)


# baker.make + ORM в async-тестах требуют sync_to_async wrapper.
amake = sync_to_async(baker.make, thread_sensitive=True)


@sync_to_async
def _count_mutes(**filters) -> int:
    return NudgeMute.objects.filter(**filters).count()


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


def test_mute_keyboard_has_two_buttons():
    from maxbot.nudges.keyboards import nudge_mute_keyboard
    keyboard = nudge_mute_keyboard(kind="pattern_detected")
    payloads = _flatten(keyboard)
    assert any(p.startswith("cb:nudge:mute:off:") for p in payloads)
    assert any(p.startswith("cb:nudge:mute:less:") for p in payloads)


def test_mute_keyboard_payload_includes_kind():
    from maxbot.nudges.keyboards import nudge_mute_keyboard
    keyboard = nudge_mute_keyboard(kind="cross_promo")
    payloads = _flatten(keyboard)
    assert "cb:nudge:mute:off:cross_promo" in payloads
    assert "cb:nudge:mute:less:cross_promo" in payloads


@pytest.mark.asyncio
async def test_on_nudge_mute_off_creates_record(monkeypatch):
    from maxbot.nudges.mute_handlers import on_nudge_mute_off

    bot_user = await amake(BotUser, max_user_id=1)
    monkeypatch.setattr(
        "maxbot.nudges.mute_handlers.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = MagicMock()
    cb.callback.payload = "cb:nudge:mute:off:cross_promo"
    cb.callback.user = MagicMock(user_id=1, full_name="Аня")
    cb.message.recipient.chat_id = 100
    cb.bot = MagicMock(send_message=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=1)
    await on_nudge_mute_off(cb, ctx)

    assert await _count_mutes(
        bot_user=bot_user, kind="cross_promo", mode="off",
        reason="user_explicit_off",
    ) == 1
    cb.bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_nudge_mute_less_creates_record(monkeypatch):
    from maxbot.nudges.mute_handlers import on_nudge_mute_less_often

    bot_user = await amake(BotUser, max_user_id=2)
    monkeypatch.setattr(
        "maxbot.nudges.mute_handlers.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = MagicMock()
    cb.callback.payload = "cb:nudge:mute:less:pattern_detected"
    cb.callback.user = MagicMock(user_id=2, full_name="Аня")
    cb.message.recipient.chat_id = 100
    cb.bot = MagicMock(send_message=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=2)
    await on_nudge_mute_less_often(cb, ctx)

    assert await _count_mutes(
        bot_user=bot_user, kind="pattern_detected", mode="less_often",
        reason="user_explicit_less",
    ) == 1
    cb.bot.send_message.assert_awaited_once()
