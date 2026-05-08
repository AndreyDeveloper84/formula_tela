"""DRF-358 T03: on_free_text food/drink fallback hook integration.

Verifies pre-hook ordering:
1. try_handle_water_text (parse_beverage) — fast-lane если match
2. looks_like_food_drink check — clarification card если match (NEW)
3. AI Concierge — full LLM call для всего остального (existing)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from maxapi.context.context import MemoryContext


@pytest.mark.asyncio
async def test_food_drink_hint_renders_clarification_card_skips_ai(monkeypatch, settings):
    """«Борщ 300грамм» → looks_like_food_drink=True → clarification card.
    AI Concierge НЕ вызывается."""
    settings.NUTRITION_ENABLED = True
    from maxbot.handlers.ai_assistant import on_free_text

    bot_user = MagicMock(max_user_id=200, nutrition_onboarded_at=None, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    # try_handle_water_text — miss (это не напиток for parse_beverage)
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.try_handle_water_text",
        AsyncMock(return_value=False),
    )
    concierge_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._invoke_ai_concierge", concierge_mock,
    )

    event = MagicMock()
    event.message.body.text = "Борщ 300грамм"
    event.message.recipient.chat_id = 100
    event.message.sender = MagicMock(user_id=200, full_name="Аня")
    event.bot = MagicMock(send_message=AsyncMock(), send_action=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_free_text(event, ctx)

    # AI Concierge skipped
    concierge_mock.assert_not_called()
    # Clarification card sent
    event.bot.send_message.assert_awaited()
    sent_text = event.bot.send_message.await_args.kwargs.get("text") or ""
    assert "курьер" in sent_text.lower() or "доставк" in sent_text.lower() or "🍽" in sent_text or "😄" in sent_text


@pytest.mark.asyncio
async def test_water_text_handled_first_no_food_card(monkeypatch, settings):
    """«стакан кофе» → try_handle_water_text returns True → водный
    fast-lane.  food_drink_hints НЕ вызывается (раньше return)."""
    settings.NUTRITION_ENABLED = True
    from maxbot.handlers.ai_assistant import on_free_text

    bot_user = MagicMock(max_user_id=200, nutrition_onboarded_at=None, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.try_handle_water_text",
        AsyncMock(return_value=True),  # water hit
    )
    looks_mock = MagicMock(return_value=True)  # этот не должен быть вызван
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.looks_like_food_drink", looks_mock,
    )
    concierge_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._invoke_ai_concierge", concierge_mock,
    )

    event = MagicMock()
    event.message.body.text = "стакан кофе"
    event.message.recipient.chat_id = 100
    event.message.sender = MagicMock(user_id=200, full_name="Аня")
    event.bot = MagicMock(send_message=AsyncMock(), send_action=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_free_text(event, ctx)

    # food_drink_hints НЕ вызывался (early return после water hit)
    looks_mock.assert_not_called()
    concierge_mock.assert_not_called()


@pytest.mark.asyncio
async def test_pain_text_falls_through_to_ai(monkeypatch, settings):
    """«Шея болит» → looks_like_food_drink=False → AI Concierge вызван
    (diagnostic-first prompt rule сработает в prompt rendering)."""
    settings.NUTRITION_ENABLED = True
    from maxbot.handlers.ai_assistant import on_free_text

    bot_user = MagicMock(max_user_id=200, nutrition_onboarded_at=None, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.try_handle_water_text",
        AsyncMock(return_value=False),
    )
    concierge_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._invoke_ai_concierge", concierge_mock,
    )

    event = MagicMock()
    event.message.body.text = "Шея болит"
    event.message.recipient.chat_id = 100
    event.message.sender = MagicMock(user_id=200, full_name="Аня")
    event.bot = MagicMock(send_message=AsyncMock(), send_action=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_free_text(event, ctx)

    # AI Concierge called (нет food/drink hint)
    concierge_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_nutrition_disabled_skips_food_hint(monkeypatch, settings):
    """NUTRITION_ENABLED=False → не показываем food clarify card,
    идём в AI Concierge как обычно (это salon бот в default)."""
    settings.NUTRITION_ENABLED = False
    from maxbot.handlers.ai_assistant import on_free_text

    bot_user = MagicMock(max_user_id=200, nutrition_onboarded_at=None, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.try_handle_water_text",
        AsyncMock(return_value=False),
    )
    concierge_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._invoke_ai_concierge", concierge_mock,
    )

    event = MagicMock()
    event.message.body.text = "Борщ 300г"
    event.message.recipient.chat_id = 100
    event.message.sender = MagicMock(user_id=200, full_name="Аня")
    event.bot = MagicMock(send_message=AsyncMock(), send_action=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_free_text(event, ctx)

    # NUTRITION off → нет clarification card, fall through to AI
    concierge_mock.assert_awaited_once()
