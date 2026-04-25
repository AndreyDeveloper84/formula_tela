"""T-06c: handler ai_assistant.py — кнопка + free-text + BotInquiry fallback."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from model_bakery import baker

from maxapi.context.context import MemoryContext

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _make_callback(*, chat_id=100, user_id=200, payload="cb:menu:ask"):
    user = MagicMock()
    user.user_id = user_id
    user.first_name = "Иван"
    user.full_name = "Иван"
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


def _make_text_message(*, chat_id=100, user_id=200, text="Как записаться?"):
    sender = MagicMock()
    sender.user_id = user_id
    sender.first_name = "Иван"
    sender.full_name = "Иван"
    body = MagicMock()
    body.text = text
    event = MagicMock()
    event.message = MagicMock()
    event.message.sender = sender
    event.message.recipient = MagicMock()
    event.message.recipient.chat_id = chat_id
    event.message.body = body
    event.bot = MagicMock()
    event.bot.send_message = AsyncMock()
    return event


# ─── on_ask_button — переход в state awaiting_question ─────────────────────


@pytest.mark.asyncio
async def test_ask_button_sets_awaiting_question_state():
    from maxbot.handlers.ai_assistant import on_ask_button
    from maxbot.states import AskStates
    event = _make_callback(user_id=20001)
    ctx = MemoryContext(chat_id=100, user_id=20001)
    await on_ask_button(event, ctx)
    assert str(await ctx.get_state()) == str(AskStates.awaiting_question)
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "вопрос" in text.lower()


@pytest.mark.asyncio
async def test_ask_button_skips_when_message_deleted():
    from maxbot.handlers.ai_assistant import on_ask_button
    event = _make_callback(user_id=20002)
    event.message = None
    ctx = MemoryContext(chat_id=0, user_id=20002)
    await on_ask_button(event, ctx)
    event.bot.send_message.assert_not_awaited()


# ─── on_free_text — основной AI flow ───────────────────────────────────────


@pytest.mark.asyncio
async def test_free_text_returns_llm_answer():
    """LLM вернул нормальный ответ → клиент получает + главное меню."""
    from maxbot.handlers.ai_assistant import on_free_text
    event = _make_text_message(user_id=20003, text="Как записаться?")
    ctx = MemoryContext(chat_id=100, user_id=20003)

    with patch("maxbot.handlers.ai_assistant._get_ai_answer",
               AsyncMock(return_value="Запись через бот, кнопка «Записаться».")):
        await on_free_text(event, ctx)

    # 2 send_message: AI_THINKING и финальный ответ
    assert event.bot.send_message.await_count == 2
    final_call = event.bot.send_message.await_args_list[1].kwargs
    assert "Запись через бот" in final_call["text"]
    # Главное меню в attachments
    assert "attachments" in final_call


@pytest.mark.asyncio
async def test_free_text_clears_state_after_answer():
    from maxbot.handlers.ai_assistant import on_free_text
    from maxbot.states import AskStates
    event = _make_text_message(user_id=20004)
    ctx = MemoryContext(chat_id=100, user_id=20004)
    await ctx.set_state(AskStates.awaiting_question)

    with patch("maxbot.handlers.ai_assistant._get_ai_answer",
               AsyncMock(return_value="ok")):
        await on_free_text(event, ctx)

    assert await ctx.get_state() is None


@pytest.mark.asyncio
async def test_free_text_creates_bot_inquiry_on_giveup():
    """LLM вернул LLM_GIVEUP_MESSAGE → создаём BotInquiry."""
    from maxbot.handlers.ai_assistant import on_free_text
    from maxbot.llm import LLM_GIVEUP_MESSAGE
    from services_app.models import BotInquiry

    event = _make_text_message(user_id=20005, chat_id=777, text="Какой ваш любимый цвет?")
    ctx = MemoryContext(chat_id=777, user_id=20005)

    with patch("maxbot.handlers.ai_assistant._get_ai_answer",
               AsyncMock(return_value=LLM_GIVEUP_MESSAGE)):
        await on_free_text(event, ctx)

    inquiries = await sync_to_async(list)(BotInquiry.objects.all())
    assert len(inquiries) == 1
    assert inquiries[0].chat_id == 777
    assert inquiries[0].question == "Какой ваш любимый цвет?"
    assert inquiries[0].sent_to_max is False  # не отправлен ещё (T-09 push back)
    # Сообщение клиенту — про менеджера, не giveup-message
    final_text = event.bot.send_message.await_args_list[1].kwargs["text"]
    assert "менеджер" in final_text.lower()


@pytest.mark.asyncio
async def test_free_text_skips_message_without_sender():
    from maxbot.handlers.ai_assistant import on_free_text
    event = _make_text_message(user_id=20006)
    event.message.sender = None
    ctx = MemoryContext(chat_id=100, user_id=20006)
    await on_free_text(event, ctx)
    event.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_text_skips_empty_message():
    from maxbot.handlers.ai_assistant import on_free_text
    event = _make_text_message(user_id=20007, text="   ")
    ctx = MemoryContext(chat_id=100, user_id=20007)
    await on_free_text(event, ctx)
    event.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_text_handles_chat_with_tools_exception():
    """Если внутри LLM/MCP exception — _get_ai_answer возвращает GIVEUP, BotInquiry создаётся."""
    from maxbot.handlers.ai_assistant import _get_ai_answer
    from maxbot.llm import LLM_GIVEUP_MESSAGE
    sender = MagicMock(user_id=20008, full_name="X")
    with patch("maxbot.handlers.ai_assistant.chat_with_tools",
               AsyncMock(side_effect=RuntimeError("LLM down"))):
        result = await _get_ai_answer("?", sender)
    assert result == LLM_GIVEUP_MESSAGE


# ─── Главное меню теперь содержит кнопку «Задать вопрос» ───────────────────


def test_main_menu_includes_ask_button():
    from maxbot.keyboards import main_menu_keyboard, PAYLOAD_MENU_ASK
    kb = main_menu_keyboard()
    payloads = [b.payload for row in kb.payload.buttons for b in row]
    assert PAYLOAD_MENU_ASK in payloads
