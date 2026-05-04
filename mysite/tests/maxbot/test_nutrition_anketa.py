"""Phase 3.1 Part 1: TIER-A анкета — handlers тесты.

Используем fake-объекты вместо реального MAX SDK runtime: каждому handler'у
передаём (callback|event, MemoryContext). Контролируем `bot.send_message`
через AsyncMock и проверяем (chat_id, text, attachments).

Ayla calls (`upsert_profile`, `get_profile`) мокаем через
monkeypatch.setattr на singleton `get_nutrition_client()`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ─── helpers ───────────────────────────────────────────────────────────────


def _fake_callback(payload: str, chat_id: int = 12345) -> MagicMock:
    """Build minimal MessageCallback double для router-handler'а."""
    cb = MagicMock()
    cb.callback.payload = payload
    cb.message.recipient.chat_id = chat_id
    cb.bot.send_message = AsyncMock()
    return cb


def _fake_message(text: str, chat_id: int = 12345, sender_id: int = 99) -> MagicMock:
    """Build minimal MessageCreated double."""
    msg = MagicMock()
    msg.message.body.text = text
    msg.message.recipient.chat_id = chat_id
    msg.message.sender.user_id = sender_id
    msg.bot.send_message = AsyncMock()
    return msg


# ─── consent step ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_anketa_sets_consent_state_and_renders_disclaimer():
    """Юзер кликнул [📝 Настроить под себя] → state=awaiting_consent,
    бот шлёт текст дисклеймера + 2 кнопки."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_entry import on_start_anketa
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:nutrition:start_anketa", chat_id=12345)
    ctx = MemoryContext(chat_id=12345, user_id=99)

    await on_start_anketa(cb, ctx)

    state = await ctx.get_state()
    assert state == NutritionAnketaStates.awaiting_consent

    cb.bot.send_message.assert_awaited_once()
    call_kwargs = cb.bot.send_message.await_args.kwargs
    text_lower = call_kwargs["text"].lower()
    # Дисклеймер должен упоминать персональные данные или закон 152-ФЗ
    assert "152" in text_lower or "дисклеймер" in text_lower or "данн" in text_lower
    # Attachments — keyboard с 2 кнопками
    assert call_kwargs.get("attachments") is not None
