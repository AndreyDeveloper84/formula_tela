"""Phase 3.2A T05: diabetes + chronic multi-select screens."""
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
    cb.bot = MagicMock(send_message=AsyncMock(), edit_message=AsyncMock())
    return cb


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,expected_type", [
    ("cb:tier_b:diabetes:no", "no"),
    ("cb:tier_b:diabetes:t1", "t1"),
    ("cb:tier_b:diabetes:t2", "t2"),
    ("cb:tier_b:diabetes:pre", "pre"),
])
async def test_diabetes_persists_type_advances_to_chronic(
    monkeypatch, payload, expected_type,
):
    from maxbot.handlers.health_screening import on_diabetes_answer

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )

    cb = _cb(payload)
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_diabetes)

    await on_diabetes_answer(cb, ctx)

    save_mock.assert_called_once()
    assert save_mock.call_args.args[1] == "diabetes_type"
    assert save_mock.call_args.args[2] == expected_type
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_chronic")


@pytest.mark.asyncio
async def test_chronic_toggle_first_select_adds_slug(monkeypatch):
    from maxbot.handlers.health_screening import on_chronic_toggle

    cb = _cb("cb:tier_b:chronic:toggle:hypertension")
    cb.bot.edit_message = AsyncMock()
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_chronic)

    await on_chronic_toggle(cb, ctx)

    data = await ctx.get_data()
    assert "chronic_selected" in data
    assert "hypertension" in data["chronic_selected"]


@pytest.mark.asyncio
async def test_chronic_toggle_second_click_removes_slug(monkeypatch):
    from maxbot.handlers.health_screening import on_chronic_toggle

    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_chronic)
    await ctx.update_data(chronic_selected=["thyroid"])

    cb = _cb("cb:tier_b:chronic:toggle:thyroid")
    await on_chronic_toggle(cb, ctx)

    data = await ctx.get_data()
    assert "thyroid" not in (data.get("chronic_selected") or [])


@pytest.mark.asyncio
async def test_chronic_done_persists_list_advances_to_allergies(monkeypatch):
    from maxbot.handlers.health_screening import on_chronic_done

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )

    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_chronic)
    await ctx.update_data(chronic_selected=["thyroid", "eating_disorder"])

    cb = _cb("cb:tier_b:chronic:done")
    await on_chronic_done(cb, ctx)

    save_mock.assert_called_once()
    assert save_mock.call_args.args[1] == "chronic"
    assert set(save_mock.call_args.args[2]) == {"thyroid", "eating_disorder"}
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_allergies")


@pytest.mark.asyncio
async def test_chronic_none_clears_and_advances(monkeypatch):
    """«Ничего» → empty list saved + advance."""
    from maxbot.handlers.health_screening import on_chronic_none

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )

    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_chronic)
    await ctx.update_data(chronic_selected=["thyroid"])

    cb = _cb("cb:tier_b:chronic:none")
    await on_chronic_none(cb, ctx)

    assert save_mock.call_args.args[1] == "chronic"
    assert save_mock.call_args.args[2] == []
    state = await ctx.get_state()
    assert str(state).endswith("awaiting_allergies")
