"""Phase 3.1 Part 2D.1 T02: try_handle_water_text — free-text water entry."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from maxapi.context.context import MemoryContext


pytestmark = pytest.mark.django_db


def _fake_message(text, chat_id=100, user_id=200):
    msg = MagicMock()
    msg.message.body.text = text
    msg.message.recipient.chat_id = chat_id
    msg.message.sender = MagicMock(user_id=user_id, full_name="Тест")
    msg.bot.send_message = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_try_handle_water_text_recognizes_coffee_and_calls_add_water(
    monkeypatch, settings,
):
    """«выпила стакан кофе» → parse_beverage hit → add_water → render + undo."""
    from maxbot.handlers.water import try_handle_water_text
    from maxbot.services.nutrition_client import WaterEntryResponse

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock(return_value=WaterEntryResponse(
        entry_id="W-fr1", ml=250, water_ml=250, kcal=10,
        milestone_text=None,
        today_total_ml=1450, today_norm_ml=2000,
        alcohol_recovery_hint=False, raw={"caffeine_mg": 95},
    ))
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    msg = _fake_message("выпила стакан кофе")
    ctx = MemoryContext(chat_id=100, user_id=200)

    handled = await try_handle_water_text(msg, ctx)

    assert handled is True
    add_mock.assert_awaited_once()
    kwargs = add_mock.await_args.kwargs
    assert kwargs["beverage_slug"] == "kofe_chernyi"
    assert kwargs["ml"] == 250

    msg.bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_try_handle_water_text_returns_false_on_unrelated_text(
    monkeypatch, settings,
):
    """«как погода» → не водный текст → return False, add_water not called."""
    from maxbot.handlers.water import try_handle_water_text

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock()
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )

    msg = _fake_message("как погода")
    ctx = MemoryContext(chat_id=100, user_id=200)

    handled = await try_handle_water_text(msg, ctx)

    assert handled is False
    add_mock.assert_not_awaited()
    msg.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_try_handle_water_text_skipped_when_nutrition_disabled(
    monkeypatch, settings,
):
    """NUTRITION_ENABLED=False → return False (без перехвата)."""
    from maxbot.handlers.water import try_handle_water_text

    settings.NUTRITION_ENABLED = False

    add_mock = AsyncMock()
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )

    msg = _fake_message("выпила кофе")
    ctx = MemoryContext(chat_id=100, user_id=200)

    handled = await try_handle_water_text(msg, ctx)

    assert handled is False
    add_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_try_handle_water_text_skipped_during_anketa_fsm(
    monkeypatch, settings,
):
    """В FSM анкеты → return False (юзер должен отвечать вопрос анкеты)."""
    from maxbot.handlers.water import try_handle_water_text
    from maxbot.states import NutritionAnketaStates

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock()
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )

    msg = _fake_message("выпила кофе")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    handled = await try_handle_water_text(msg, ctx)

    assert handled is False
    add_mock.assert_not_awaited()
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age


@pytest.mark.asyncio
async def test_on_free_text_intercepts_water_text_before_ai(monkeypatch, settings):
    """on_free_text вызывает try_handle_water_text первым; если True →
    AI Concierge (run_ai_turn) не вызывается."""
    from maxbot.handlers.ai_assistant import on_free_text

    settings.NUTRITION_ENABLED = True

    # Mock try_handle_water_text → True (handled)
    handler_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.try_handle_water_text", handler_mock,
    )

    # run_ai_turn — should NOT be called when water handled
    run_ai_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.run_ai_turn", run_ai_mock,
    )

    msg = _fake_message("выпила кофе")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_free_text(msg, ctx)

    handler_mock.assert_awaited_once()
    run_ai_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_free_text_falls_through_to_ai_when_water_returns_false(
    monkeypatch, settings,
):
    """try_handle_water_text=False → run_ai_turn вызывается (default route)."""
    from maxbot.handlers.ai_assistant import on_free_text

    settings.NUTRITION_ENABLED = True

    handler_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.try_handle_water_text", handler_mock,
    )

    run_ai_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.run_ai_turn", run_ai_mock,
    )

    # Mock other deps along happy AI path
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    # detect_intent — None (нет intent match)
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.detect_intent",
        lambda txt: None,
    )

    msg = _fake_message("как погода")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_free_text(msg, ctx)

    handler_mock.assert_awaited_once()
    run_ai_mock.assert_awaited_once()
