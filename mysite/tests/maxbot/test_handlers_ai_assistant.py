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
    event.bot.send_action = AsyncMock()
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
    """LLM вернул нормальный ответ → клиент получает один send_message + меню.

    После замены AI_THINKING на send_action(TYPING_ON) — финальный ответ
    единственное сообщение в чате (не два).
    """
    from maxapi.enums.sender_action import SenderAction
    from maxbot.handlers.ai_assistant import on_free_text
    event = _make_text_message(user_id=20003, text="Как записаться?")
    ctx = MemoryContext(chat_id=100, user_id=20003)

    with patch("maxbot.handlers.ai_assistant._get_ai_answer",
               AsyncMock(return_value="Запись через бот, кнопка «Записаться».")):
        await on_free_text(event, ctx)

    # Typing indicator — нативный, не сообщение
    event.bot.send_action.assert_awaited_once_with(
        chat_id=100, action=SenderAction.TYPING_ON,
    )
    # Финальный ответ — единственный send_message
    assert event.bot.send_message.await_count == 1
    final_call = event.bot.send_message.await_args.kwargs
    assert "Запись через бот" in final_call["text"]
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
               AsyncMock(return_value=LLM_GIVEUP_MESSAGE)), \
         patch("maxbot.handlers.ai_assistant.send_notification_telegram") as _:
        await on_free_text(event, ctx)

    inquiries = await sync_to_async(list)(BotInquiry.objects.all())
    assert len(inquiries) == 1
    assert inquiries[0].chat_id == 777
    assert inquiries[0].question == "Какой ваш любимый цвет?"
    assert inquiries[0].sent_to_max is False  # не отправлен ещё (T-09 push back)
    # Сообщение клиенту — единственный send_message с упоминанием менеджера
    assert event.bot.send_message.await_count == 1
    final_text = event.bot.send_message.await_args.kwargs["text"]
    assert "менеджер" in final_text.lower()


@pytest.mark.asyncio
async def test_free_text_sends_telegram_alert_on_giveup():
    """При создании BotInquiry — Telegram-алерт менеджеру (через notifications/)."""
    from maxbot.handlers.ai_assistant import on_free_text
    from maxbot.llm import LLM_GIVEUP_MESSAGE

    event = _make_text_message(user_id=20009, chat_id=888, text="Что-то странное")
    ctx = MemoryContext(chat_id=888, user_id=20009)
    with patch("maxbot.handlers.ai_assistant._get_ai_answer",
               AsyncMock(return_value=LLM_GIVEUP_MESSAGE)), \
         patch("maxbot.handlers.ai_assistant.send_notification_telegram") as mock_tg:
        await on_free_text(event, ctx)
    mock_tg.assert_called_once()
    msg = mock_tg.call_args.args[0]
    assert "Что-то странное" in msg
    assert "менеджер" in msg.lower() or "вопрос" in msg.lower()


@pytest.mark.asyncio
async def test_free_text_skips_message_without_sender():
    from maxbot.handlers.ai_assistant import on_free_text
    event = _make_text_message(user_id=20006)
    event.message.sender = None
    ctx = MemoryContext(chat_id=100, user_id=20006)
    await on_free_text(event, ctx)
    event.bot.send_message.assert_not_awaited()
    event.bot.send_action.assert_not_awaited()  # typing-индикатор не должен светиться


@pytest.mark.asyncio
async def test_free_text_skips_empty_message():
    from maxbot.handlers.ai_assistant import on_free_text
    event = _make_text_message(user_id=20007, text="   ")
    ctx = MemoryContext(chat_id=100, user_id=20007)
    await on_free_text(event, ctx)
    event.bot.send_message.assert_not_awaited()
    event.bot.send_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_text_typing_indicator_survives_send_action_failure():
    """Если send_action упал (сетевой сбой) — AI flow должен продолжиться.

    Typing-индикатор это best-effort UX, его падение не должно блокировать
    ответ клиенту.
    """
    from maxbot.handlers.ai_assistant import on_free_text
    event = _make_text_message(user_id=20010, text="Сколько стоит?")
    event.bot.send_action = AsyncMock(side_effect=RuntimeError("network blip"))
    ctx = MemoryContext(chat_id=100, user_id=20010)

    with patch("maxbot.handlers.ai_assistant._get_ai_answer",
               AsyncMock(return_value="3000 руб.")):
        await on_free_text(event, ctx)

    # Финальный ответ всё равно ушёл
    event.bot.send_message.assert_awaited_once()
    assert "3000" in event.bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_free_text_handles_chat_rag_exception():
    """Если внутри LLM/MCP exception — _get_ai_answer возвращает GIVEUP."""
    from maxbot.handlers.ai_assistant import _get_ai_answer
    from maxbot.llm import LLM_GIVEUP_MESSAGE
    sender = MagicMock(user_id=20008, full_name="X")
    with patch("maxbot.handlers.ai_assistant.chat_rag",
               AsyncMock(side_effect=RuntimeError("LLM down"))):
        result = await _get_ai_answer("?", sender)
    assert result == LLM_GIVEUP_MESSAGE


# ─── Главное меню теперь содержит кнопку «Задать вопрос» ───────────────────


def test_main_menu_includes_ask_button():
    from maxbot.keyboards import main_menu_keyboard, PAYLOAD_MENU_ASK
    kb = main_menu_keyboard()
    payloads = [b.payload for row in kb.payload.buttons for b in row]
    assert PAYLOAD_MENU_ASK in payloads


# ─── Response cache — _get_ai_answer integration ──────────────────────────


@pytest.fixture
def _clear_cache():
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.mark.asyncio
async def test_get_ai_answer_returns_cached_without_calling_chat_rag(_clear_cache):
    """Кэш-хит → не зовём chat_rag, не платим ~6.7s OpenAI/MCP."""
    from maxbot.handlers.ai_assistant import _get_ai_answer
    from maxbot.response_cache import set_cached_answer

    await set_cached_answer("Как записаться?", "Кэш-ответ")
    sender = MagicMock(user_id=30001, full_name="X")

    with patch("maxbot.handlers.ai_assistant.chat_rag",
               AsyncMock(return_value="не должен быть вызван")) as mock_rag:
        result = await _get_ai_answer("Как записаться?", sender)

    assert result == "Кэш-ответ"
    mock_rag.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_ai_answer_caches_successful_answer(_clear_cache):
    """После успешного ответа — следующий вызов того же вопроса кэш-хит."""
    from maxbot.handlers.ai_assistant import _get_ai_answer
    from maxbot.response_cache import get_cached_answer

    sender = MagicMock(user_id=30002, full_name="X")
    with patch("maxbot.handlers.ai_assistant.chat_rag",
               AsyncMock(return_value="свежий ответ от LLM")):
        result = await _get_ai_answer("Сколько стоит массаж спины?", sender)

    assert result == "свежий ответ от LLM"
    # Проверяем что ответ положили в кэш
    assert await get_cached_answer("Сколько стоит массаж спины?") == "свежий ответ от LLM"


@pytest.mark.asyncio
async def test_get_ai_answer_does_not_cache_giveup(_clear_cache):
    """LLM_GIVEUP_MESSAGE не кэшируем — пусть retry имеет шанс."""
    from maxbot.handlers.ai_assistant import _get_ai_answer
    from maxbot.llm import LLM_GIVEUP_MESSAGE
    from maxbot.response_cache import get_cached_answer

    sender = MagicMock(user_id=30003, full_name="X")
    with patch("maxbot.handlers.ai_assistant.chat_rag",
               AsyncMock(return_value=LLM_GIVEUP_MESSAGE)):
        result = await _get_ai_answer("Что-то странное", sender)

    assert result == LLM_GIVEUP_MESSAGE
    assert await get_cached_answer("Что-то странное") is None


@pytest.mark.asyncio
async def test_get_ai_answer_does_not_cache_on_exception(_clear_cache):
    """Exception → GIVEUP, не кэшируется."""
    from maxbot.handlers.ai_assistant import _get_ai_answer
    from maxbot.llm import LLM_GIVEUP_MESSAGE
    from maxbot.response_cache import get_cached_answer

    sender = MagicMock(user_id=30004, full_name="X")
    with patch("maxbot.handlers.ai_assistant.chat_rag",
               AsyncMock(side_effect=RuntimeError("OpenAI down"))):
        result = await _get_ai_answer("Какой режим работы?", sender)

    assert result == LLM_GIVEUP_MESSAGE
    assert await get_cached_answer("Какой режим работы?") is None


@pytest.mark.asyncio
async def test_get_ai_answer_cache_hits_normalized_variants(_clear_cache):
    """Кэш по «как записаться?» хитит при «КАК ЗАПИСАТЬСЯ.», «как  записаться»."""
    from maxbot.handlers.ai_assistant import _get_ai_answer
    from maxbot.response_cache import set_cached_answer

    await set_cached_answer("как записаться", "Через бота или по телефону.")
    sender = MagicMock(user_id=30005, full_name="X")

    with patch("maxbot.handlers.ai_assistant.chat_rag",
               AsyncMock(return_value="не должен быть вызван")) as mock_rag:
        for variant in ["Как записаться?", "КАК ЗАПИСАТЬСЯ.", "как  записаться  "]:
            result = await _get_ai_answer(variant, sender)
            assert result == "Через бота или по телефону.", f"variant={variant!r}"

    mock_rag.assert_not_awaited()
