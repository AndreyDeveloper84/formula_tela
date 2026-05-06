"""Phase 3.2A T06: allergies (3-option + free-text) + meds screens."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from maxapi.context.context import MemoryContext

from maxbot.states import NutritionAnketaStates


def _cb(payload):
    cb = MagicMock()
    cb.callback.payload = payload
    cb.callback.user = MagicMock(user_id=200, full_name="Аня")
    cb.message.recipient.chat_id = 100
    cb.bot = MagicMock(send_message=AsyncMock())
    return cb


@pytest.mark.asyncio
async def test_allergies_none_persists_empty_list_advances_to_meds(monkeypatch):
    from maxbot.handlers.health_screening import on_allergies_choice

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )

    cb = _cb("cb:tier_b:allergies:none")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_allergies)

    await on_allergies_choice(cb, ctx)

    save_mock.assert_called_once()
    assert save_mock.call_args.args[1] == "allergies"
    assert save_mock.call_args.args[2] == []
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_meds")


@pytest.mark.asyncio
async def test_allergies_text_advances_to_text_state(monkeypatch):
    from maxbot.handlers.health_screening import on_allergies_choice

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _cb("cb:tier_b:allergies:text")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_allergies)

    await on_allergies_choice(cb, ctx)

    state = await ctx.get_state()
    assert str(state).endswith("awaiting_allergies_text")


@pytest.mark.asyncio
async def test_allergies_vague_persists_flag_advances_to_meds(monkeypatch):
    from maxbot.handlers.health_screening import on_allergies_choice

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )

    cb = _cb("cb:tier_b:allergies:vague")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_allergies)

    await on_allergies_choice(cb, ctx)

    save_mock.assert_called_once()
    assert save_mock.call_args.args[1] == "allergies_vague"
    assert save_mock.call_args.args[2] is True
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_meds")


@pytest.mark.asyncio
async def test_allergies_text_input_parses_and_advances(monkeypatch):
    """Free-text «лактоза, орехи» → parse_allergies → list of slugs."""
    from maxbot.handlers.health_screening import on_allergies_text_input

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.parse_allergies",
        AsyncMock(return_value=["lactose", "nuts"]),
    )

    event = MagicMock()
    event.message.body.text = "лактоза, орехи"
    event.message.recipient.chat_id = 100
    event.message.sender = MagicMock(user_id=200, full_name="Аня")
    event.bot = MagicMock(send_message=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_allergies_text)

    await on_allergies_text_input(event, ctx)

    save_mock.assert_called_once()
    assert save_mock.call_args.args[1] == "allergies"
    assert save_mock.call_args.args[2] == ["lactose", "nuts"]
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_meds")


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,expected_value,expected_key", [
    ("cb:tier_b:yes", True, "meds"),
    ("cb:tier_b:no", False, "meds"),
    ("cb:tier_b:skip", True, "meds_skipped"),
])
async def test_meds_persists_and_routes_to_menopause_or_complete(
    monkeypatch, payload, expected_value, expected_key,
):
    """В Task 6 — независимо от age/gender state advances to awaiting_menopause.
    Conditional skip-to-complete будет в Task 7."""
    from maxbot.handlers.health_screening import on_meds_answer

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )
    # Force menopause path (age 50, female)
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._fetch_age_and_gender",
        AsyncMock(return_value=(50, "female")),
    )

    cb = _cb(payload)
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_meds)

    await on_meds_answer(cb, ctx)

    save_mock.assert_called_once()
    assert save_mock.call_args.args[1] == expected_key
    assert save_mock.call_args.args[2] == expected_value
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_menopause")
