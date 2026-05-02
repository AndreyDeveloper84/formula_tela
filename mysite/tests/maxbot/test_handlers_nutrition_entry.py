"""Phase 3 T01: handler nutrition_entry — entry-screen дневника + 2 заглушки.

Покрывает:
- on_show_nutrition_welcome — реакция на cb:menu:nutrition (welcome screen)
- on_try_now_stub — заглушка cb:nutrition:try_now (T03 будет реализована)
- on_start_anketa_stub — заглушка cb:nutrition:start_anketa (T04 анкета)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from maxapi.context.context import MemoryContext

pytestmark = pytest.mark.django_db


def _make_callback(*, chat_id=100, user_id=200, payload=""):
    user = MagicMock()
    user.user_id = user_id
    user.first_name = "Тест"
    user.full_name = "Тест"
    event = MagicMock()
    event.message = MagicMock()
    event.message.recipient = MagicMock()
    event.message.recipient.chat_id = chat_id
    event.callback = MagicMock()
    event.callback.user = user
    event.callback.payload = payload
    event.bot = MagicMock()
    event.bot.send_message = AsyncMock()
    return event


@pytest.mark.asyncio
async def test_welcome_screen_text_contains_key_phrases():
    """Welcome screen дневника начинается с emoji + краткое описание ценности."""
    from maxbot.handlers.nutrition_entry import on_show_nutrition_welcome

    event = _make_callback(payload="cb:menu:nutrition", user_id=9001)
    ctx = MemoryContext(chat_id=100, user_id=9001)
    await on_show_nutrition_welcome(event, ctx)

    event.bot.send_message.assert_awaited_once()
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "🍎 Дневник питания" in text
    assert "Сфоткай еду" in text
    # Конкретика «не средние 2000 ккал» — главный sales-pitch для анкеты
    assert "2000 ккал" in text


@pytest.mark.asyncio
async def test_welcome_screen_keyboard_has_two_action_buttons():
    """Welcome screen прикрепляет nutrition_welcome_keyboard — 3 payload'а."""
    from maxbot.handlers.nutrition_entry import on_show_nutrition_welcome

    event = _make_callback(payload="cb:menu:nutrition", user_id=9002)
    ctx = MemoryContext(chat_id=100, user_id=9002)
    await on_show_nutrition_welcome(event, ctx)

    attachments = event.bot.send_message.await_args.kwargs["attachments"]
    assert len(attachments) == 1
    payloads = [
        getattr(b, "payload", None)
        for row in attachments[0].payload.buttons
        for b in row
    ]
    assert "cb:nutrition:try_now" in payloads
    assert "cb:nutrition:start_anketa" in payloads
    assert "cb:back" in payloads


@pytest.mark.asyncio
async def test_welcome_skips_if_message_deleted():
    """Если callback пришёл без message (удалили) — silent skip, без send."""
    from maxbot.handlers.nutrition_entry import on_show_nutrition_welcome

    event = _make_callback(user_id=9003)
    event.message = None
    ctx = MemoryContext(chat_id=0, user_id=9003)
    await on_show_nutrition_welcome(event, ctx)
    event.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_try_now_stub_returns_friendly_placeholder():
    """Phase 3 T03 ещё не сделана — заглушка с понятным сообщением."""
    from maxbot.handlers.nutrition_entry import on_try_now_stub

    event = _make_callback(payload="cb:nutrition:try_now", user_id=9004)
    ctx = MemoryContext(chat_id=100, user_id=9004)
    await on_try_now_stub(event, ctx)

    event.bot.send_message.assert_awaited_once()
    text = event.bot.send_message.await_args.kwargs["text"]
    # Заглушка указывает что сейчас можно делать (пришли фото — старый scanner работает)
    assert "Скоро" in text
    assert "фото" in text.lower()


@pytest.mark.asyncio
async def test_start_anketa_stub_returns_friendly_placeholder():
    """T04 ещё не сделана — заглушка с честным «скоро»."""
    from maxbot.handlers.nutrition_entry import on_start_anketa_stub

    event = _make_callback(payload="cb:nutrition:start_anketa", user_id=9005)
    ctx = MemoryContext(chat_id=100, user_id=9005)
    await on_start_anketa_stub(event, ctx)

    event.bot.send_message.assert_awaited_once()
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "Анкета" in text
    assert "скоро" in text.lower()


@pytest.mark.asyncio
async def test_router_registered_in_handlers_init():
    """nutrition_entry router зарегистрирован и идёт ПЕРЕД food_scanner и ai_assistant."""
    from maxbot.handlers import get_routers
    from maxbot.handlers.nutrition_entry import router as nutrition_router
    from maxbot.handlers.food_scanner import router as food_scanner_router
    from maxbot.handlers.ai_assistant import router as ai_assistant_router

    routers = get_routers()
    assert nutrition_router in routers
    nutrition_idx = routers.index(nutrition_router)
    food_idx = routers.index(food_scanner_router)
    ai_idx = routers.index(ai_assistant_router)
    assert nutrition_idx < food_idx, "nutrition_entry must come before food_scanner"
    assert nutrition_idx < ai_idx, "nutrition_entry must come before ai_assistant"
