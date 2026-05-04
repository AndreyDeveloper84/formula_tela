"""Phase 3 T01/T04: handler nutrition_entry — entry-screen дневника.

Покрывает:
- on_show_nutrition_welcome — реакция на cb:menu:nutrition (welcome screen)
- on_try_now_stub — заглушка cb:nutrition:try_now (T03 будет реализована)
- on_start_anketa — реальный handler запуска TIER-A анкеты (T04 FSM)
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
async def test_welcome_screen_text_contains_key_phrases(monkeypatch):
    """Welcome screen дневника начинается с emoji + краткое описание ценности."""
    from maxbot.handlers.nutrition_entry import on_show_nutrition_welcome

    bot_user = MagicMock(nutrition_onboarded_at=None, max_user_id=9001)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_entry._resolve_bot_user_for_entry",
        AsyncMock(return_value=bot_user),
    )

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
async def test_welcome_screen_keyboard_has_two_action_buttons(monkeypatch):
    """Welcome screen прикрепляет nutrition_welcome_keyboard — 3 payload'а."""
    from maxbot.handlers.nutrition_entry import on_show_nutrition_welcome

    bot_user = MagicMock(nutrition_onboarded_at=None, max_user_id=9002)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_entry._resolve_bot_user_for_entry",
        AsyncMock(return_value=bot_user),
    )

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
async def test_start_anketa_sets_consent_state_and_sends_disclaimer():
    """T04 реализована — on_start_anketa устанавливает state и шлёт дисклеймер."""
    from maxbot.handlers.nutrition_entry import on_start_anketa
    from maxbot.states import NutritionAnketaStates

    event = _make_callback(payload="cb:nutrition:start_anketa", user_id=9005)
    ctx = MemoryContext(chat_id=100, user_id=9005)
    await on_start_anketa(event, ctx)

    state = await ctx.get_state()
    assert state == NutritionAnketaStates.awaiting_consent

    event.bot.send_message.assert_awaited_once()
    call_kwargs = event.bot.send_message.await_args.kwargs
    text = call_kwargs["text"]
    assert "152" in text or "дисклеймер" in text.lower() or "данн" in text.lower()
    assert call_kwargs.get("attachments") is not None


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


# ─── Phase 3.1 Part 1 T14: resume для onboarded юзера ──────────────────────


@pytest.mark.asyncio
async def test_onboarded_user_sees_resume_screen_not_anketa(monkeypatch):
    """Юзер с nutrition_onboarded_at != None → бот шлёт «Дневник готов,
    пришли фото» вместо welcome-screen."""
    from unittest.mock import AsyncMock, MagicMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_entry import on_show_nutrition_welcome

    bot_user = MagicMock(
        nutrition_onboarded_at="2026-05-03T12:00:00Z",
        max_user_id=99,
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_entry._resolve_bot_user_for_entry",
        AsyncMock(return_value=bot_user),
    )

    cb = MagicMock()
    cb.callback.payload = "cb:menu:nutrition"
    cb.callback.user.user_id = 99
    cb.message.recipient.chat_id = 12345
    cb.bot.send_message = AsyncMock()

    ctx = MemoryContext(chat_id=12345, user_id=99)

    await on_show_nutrition_welcome(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    # Resume-сообщение, не welcome
    assert "Дневник" in text
    # Welcome-text про «4 вопроса 30 секунд» НЕ показывается
    assert "30 сек" not in text and "анкет" not in text.lower()


@pytest.mark.asyncio
async def test_new_user_sees_welcome_screen(monkeypatch):
    """Юзер с nutrition_onboarded_at=None → стандартный welcome с 2 кнопками."""
    from unittest.mock import AsyncMock, MagicMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_entry import on_show_nutrition_welcome

    bot_user = MagicMock(nutrition_onboarded_at=None, max_user_id=99)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_entry._resolve_bot_user_for_entry",
        AsyncMock(return_value=bot_user),
    )

    cb = MagicMock()
    cb.callback.payload = "cb:menu:nutrition"
    cb.callback.user.user_id = 99
    cb.message.recipient.chat_id = 12345
    cb.bot.send_message = AsyncMock()

    ctx = MemoryContext(chat_id=12345, user_id=99)

    await on_show_nutrition_welcome(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "30 сек" in text or "Сфоткай" in text  # text from WELCOME_TEXT
    assert cb.bot.send_message.await_args.kwargs.get("attachments") is not None
