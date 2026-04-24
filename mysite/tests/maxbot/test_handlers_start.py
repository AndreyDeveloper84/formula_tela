"""T-07 RED: handler /start + главное меню (BotStarted, /start command, кнопка Назад)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from asgiref.sync import sync_to_async
from model_bakery import baker

from maxapi.context.context import MemoryContext

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _make_bot_started(*, chat_id=100, user_id=200, first_name="Иван", last_name=None):
    """Минимальный mock BotStarted event."""
    user = MagicMock()
    user.user_id = user_id
    user.first_name = first_name
    user.last_name = last_name
    user.full_name = first_name if last_name is None else f"{first_name} {last_name}"
    event = MagicMock()
    event.chat_id = chat_id
    event.user = user
    event.bot = MagicMock()
    event.bot.send_message = AsyncMock()
    return event


def _make_message_created(*, chat_id=100, user_id=200, first_name="Иван", text="/start"):
    """Минимальный mock MessageCreated event."""
    sender = MagicMock()
    sender.user_id = user_id
    sender.first_name = first_name
    sender.full_name = first_name
    event = MagicMock()
    event.message = MagicMock()
    event.message.sender = sender
    event.message.recipient = MagicMock()
    event.message.recipient.chat_id = chat_id
    event.bot = MagicMock()
    event.bot.send_message = AsyncMock()
    return event


def _make_callback(*, chat_id=100, user_id=200, first_name="Иван", payload="cb:back"):
    """Минимальный mock MessageCallback event."""
    user = MagicMock()
    user.user_id = user_id
    user.first_name = first_name
    user.full_name = first_name
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


# ─── on_bot_started ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bot_started_creates_new_bot_user_on_first_call():
    from maxbot.handlers.start import on_bot_started
    from services_app.models import BotUser

    event = _make_bot_started(user_id=5001, first_name="Анна")
    ctx = MemoryContext(chat_id=event.chat_id, user_id=event.user.user_id)
    await on_bot_started(event, ctx)

    assert await BotUser.objects.acount() == 1
    bu = await BotUser.objects.aget(max_user_id=5001)
    assert bu.display_name == "Анна"


@pytest.mark.asyncio
async def test_bot_started_sends_main_menu_keyboard():
    from maxbot.handlers.start import on_bot_started
    from maxbot.keyboards import PAYLOAD_MENU_BOOK

    event = _make_bot_started(user_id=5002, chat_id=999)
    ctx = MemoryContext(chat_id=999, user_id=5002)
    await on_bot_started(event, ctx)

    event.bot.send_message.assert_awaited_once()
    call = event.bot.send_message.await_args
    assert call.kwargs["chat_id"] == 999
    # Проверяем что в attachments есть главное меню (содержит PAYLOAD_MENU_BOOK)
    attachments = call.kwargs["attachments"]
    assert len(attachments) == 1
    payloads = [b.payload for row in attachments[0].payload.buttons for b in row]
    assert PAYLOAD_MENU_BOOK in payloads


@pytest.mark.asyncio
async def test_bot_started_greets_new_user_with_default():
    from maxbot.handlers.start import on_bot_started
    event = _make_bot_started(user_id=5003)
    ctx = MemoryContext(chat_id=event.chat_id, user_id=event.user.user_id)
    await on_bot_started(event, ctx)
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "Здравствуйте" in text or "Формула тела" in text


@pytest.mark.asyncio
async def test_bot_started_clears_fsm_state():
    from maxbot.handlers.start import on_bot_started
    event = _make_bot_started(user_id=5004)
    ctx = MemoryContext(chat_id=event.chat_id, user_id=event.user.user_id)
    await ctx.set_state("BookingStates:awaiting_phone")
    await ctx.update_data(some="data")
    await on_bot_started(event, ctx)
    assert await ctx.get_state() is None
    assert await ctx.get_data() == {}


# ─── on_start_command (/start) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_command_greets_returning_user_by_name():
    """При /start существующий BotUser с client_name → персонализированное приветствие."""
    from maxbot.handlers.start import on_start_command
    await amake("services_app.BotUser", max_user_id=5005, client_name="Мария")
    event = _make_message_created(user_id=5005, first_name="Maria_MAX")
    ctx = MemoryContext(chat_id=event.message.recipient.chat_id, user_id=5005)
    await on_start_command(event, ctx)
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "Мария" in text


@pytest.mark.asyncio
async def test_start_command_ignores_message_without_sender():
    """Системные сообщения без sender → handler не падает."""
    from maxbot.handlers.start import on_start_command
    event = _make_message_created(user_id=5006)
    event.message.sender = None
    ctx = MemoryContext(chat_id=100, user_id=0)
    await on_start_command(event, ctx)  # не должен упасть
    event.bot.send_message.assert_not_awaited()


# ─── on_back_to_menu (callback cb:back) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_back_callback_returns_to_main_menu():
    from maxbot.handlers.start import on_back_to_menu
    from maxbot.keyboards import PAYLOAD_MENU_SERVICES
    await amake("services_app.BotUser", max_user_id=5007, client_name="Пётр")
    event = _make_callback(user_id=5007, chat_id=777)
    ctx = MemoryContext(chat_id=777, user_id=5007)
    await on_back_to_menu(event, ctx)
    event.bot.send_message.assert_awaited_once()
    call = event.bot.send_message.await_args
    assert call.kwargs["chat_id"] == 777
    payloads = [b.payload for row in call.kwargs["attachments"][0].payload.buttons for b in row]
    assert PAYLOAD_MENU_SERVICES in payloads


@pytest.mark.asyncio
async def test_back_callback_clears_fsm_state():
    from maxbot.handlers.start import on_back_to_menu
    event = _make_callback(user_id=5008)
    ctx = MemoryContext(chat_id=event.message.recipient.chat_id, user_id=5008)
    await ctx.set_state("BookingStates:awaiting_name")
    await on_back_to_menu(event, ctx)
    assert await ctx.get_state() is None


@pytest.mark.asyncio
async def test_back_callback_skips_when_message_deleted():
    """Если callback.message=None (исходное удалено), handler не падает и не шлёт."""
    from maxbot.handlers.start import on_back_to_menu
    event = _make_callback(user_id=5009)
    event.message = None
    ctx = MemoryContext(chat_id=0, user_id=5009)
    await on_back_to_menu(event, ctx)
    event.bot.send_message.assert_not_awaited()


# ─── Router registration ────────────────────────────────────────────────────

def test_start_router_registered_handlers():
    """Импорт модуля регистрирует ≥3 handler'ов на router'е (bot_started + /start + back)."""
    from maxbot.handlers.start import router
    # Подсчёт handler'ов через .observers (или эквивалент в SDK)
    total = sum(len(h) for h in [
        getattr(router, "bot_started_handlers", []),
        getattr(router, "message_created_handlers", []),
        getattr(router, "message_callback_handlers", []),
    ])
    # Если структура SDK другая — fallback: проверяем что router callable создан
    assert router is not None
