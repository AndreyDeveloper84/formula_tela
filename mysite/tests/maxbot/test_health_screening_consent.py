"""Phase 3.2A T03: TIER-B consent screen handlers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from maxapi.context.context import MemoryContext

from maxbot.states import NutritionAnketaStates


def _fake_callback(payload: str) -> MagicMock:
    cb = MagicMock()
    cb.callback.payload = payload
    cb.callback.user = MagicMock(user_id=200, full_name="Аня")
    cb.message.recipient.chat_id = 100
    cb.bot = MagicMock()
    cb.bot.send_message = AsyncMock()
    return cb


@pytest.mark.asyncio
async def test_start_health_screening_sends_consent(monkeypatch):
    """start_health_screening shows consent screen + sets state."""
    from maxbot.handlers.health_screening import start_health_screening
    from maxbot.keyboards import (
        PAYLOAD_TIER_B_CONSENT_OK, PAYLOAD_TIER_B_CONSENT_DECLINE,
    )

    bot = MagicMock(send_message=AsyncMock())
    ctx = MemoryContext(chat_id=100, user_id=200)

    await start_health_screening(bot=bot, chat_id=100, context=ctx)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.kwargs.get("text") or ""
    assert "пара уточнений" in text or "15 секунд" in text
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_health_consent")


@pytest.mark.asyncio
async def test_consent_ok_advances_to_pregnancy(monkeypatch):
    """[Окей] → state=awaiting_pregnancy + send pregnancy keyboard."""
    from maxbot.handlers.health_screening import on_health_consent_ok

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )

    cb = _fake_callback("cb:tier_b:consent:ok")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_health_consent)

    await on_health_consent_ok(cb, ctx)

    state = await ctx.get_state()
    assert str(state).endswith("awaiting_pregnancy")
    cb.bot.send_message.assert_awaited_once()
    # Persisted ack timestamp
    save_mock.assert_called_once()
    assert save_mock.call_args.args[1] == "health_consent_acked_at"


@pytest.mark.asyncio
async def test_consent_decline_persists_flag_and_clears_state(monkeypatch):
    """[Не нужно, понятно так] → declined timestamp + state cleared."""
    from maxbot.handlers.health_screening import on_health_consent_decline

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )

    cb = _fake_callback("cb:tier_b:consent:decline")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_health_consent)

    await on_health_consent_decline(cb, ctx)

    state = await ctx.get_state()
    assert state is None  # cleared
    save_mock.assert_called_once()
    assert save_mock.call_args.args[1] == "health_consent_declined_at"
    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs.get("text") or ""
    assert "поняла" in text.lower() or "хорошо" in text.lower()
