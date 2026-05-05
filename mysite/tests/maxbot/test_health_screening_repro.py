"""Phase 3.2A T04: pregnancy + breastfeeding screens."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from maxapi.context.context import MemoryContext

from maxbot.states import NutritionAnketaStates


def _cb(payload, state):
    cb = MagicMock()
    cb.callback.payload = payload
    cb.callback.user = MagicMock(user_id=200, full_name="Аня")
    cb.message.recipient.chat_id = 100
    cb.bot = MagicMock(send_message=AsyncMock())
    return cb


@pytest.mark.asyncio
async def test_pregnancy_yes_persists_flag_advances_to_breastfeeding(monkeypatch):
    from maxbot.handlers.health_screening import on_pregnancy_answer

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )

    cb = _cb("cb:tier_b:yes", NutritionAnketaStates.awaiting_pregnancy)
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_pregnancy)

    await on_pregnancy_answer(cb, ctx)

    save_mock.assert_called_once()
    assert save_mock.call_args.args[1] == "pregnant"
    assert save_mock.call_args.args[2] is True
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_breastfeeding")


@pytest.mark.asyncio
async def test_pregnancy_no_persists_false_advances_to_breastfeeding(monkeypatch):
    from maxbot.handlers.health_screening import on_pregnancy_answer

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )

    cb = _cb("cb:tier_b:no", NutritionAnketaStates.awaiting_pregnancy)
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_pregnancy)

    await on_pregnancy_answer(cb, ctx)

    assert save_mock.call_args.args[2] is False
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_breastfeeding")


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,expected_value,expected_key", [
    ("cb:tier_b:yes", True, "breastfeeding"),
    ("cb:tier_b:no", False, "breastfeeding"),
    ("cb:tier_b:skip", True, "breastfeeding_skipped"),
])
async def test_breastfeeding_persists_and_advances_to_diabetes(
    monkeypatch, payload, expected_value, expected_key,
):
    from maxbot.handlers.health_screening import on_breastfeeding_answer

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )

    cb = _cb(payload, NutritionAnketaStates.awaiting_breastfeeding)
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_breastfeeding)

    await on_breastfeeding_answer(cb, ctx)

    save_mock.assert_called_once()
    assert save_mock.call_args.args[1] == expected_key
    assert save_mock.call_args.args[2] == expected_value
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_diabetes")
