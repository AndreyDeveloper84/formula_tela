"""T-06c + T10: handler ai_assistant.py — кнопка + free-text → AI Concierge."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from asgiref.sync import sync_to_async
from model_bakery import baker

from maxapi.context.context import MemoryContext

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


def _ai_dto(content: str = "ответ", action_type=None, action_data=None,
            conv_id=None):
    """Mock ChatResponseDTO от ai_concierge.send_message."""
    from maxbot.ai_concierge import ChatResponseDTO
    return ChatResponseDTO(
        conversation_id=conv_id or uuid4(), content=content,
        action_type=action_type, action_data=action_data,
    )


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
    event.bot.edit_message = AsyncMock()
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


# ─── on_free_text — text-only response (no action) ────────────────────────


@pytest.mark.asyncio
async def test_free_text_text_only_response_sends_with_main_menu():
    """LLM вернул plain text → send_with_main_menu(text), без extra_attachments."""
    from maxapi.enums.sender_action import SenderAction
    from maxbot.handlers.ai_assistant import on_free_text

    event = _make_text_message(user_id=20003, text="Привет, как дела")
    ctx = MemoryContext(chat_id=100, user_id=20003)

    dto = _ai_dto(content="Здравствуйте! Чем помочь?")
    with patch("maxbot.handlers.ai_assistant.ai_concierge.send_message",
               AsyncMock(return_value=dto)):
        await on_free_text(event, ctx)

    event.bot.send_action.assert_awaited_once_with(
        chat_id=100, action=SenderAction.TYPING_ON,
    )
    # Один send_message с текстом ответа + main_menu в attachments
    assert event.bot.send_message.await_count == 1
    call = event.bot.send_message.await_args.kwargs
    assert "Здравствуйте" in call["text"]
    assert call["attachments"]  # main_menu должен быть


# ─── on_free_text — action rendering ──────────────────────────────────────


@pytest.mark.asyncio
async def test_free_text_show_masters_action_renders_card():
    """LLM tool_call show_masters → render_action → send_message с card+menu."""
    from maxbot.handlers.ai_assistant import on_free_text

    event = _make_text_message(user_id=20004, text="хочу к мастеру массажа")
    ctx = MemoryContext(chat_id=100, user_id=20004)

    dto = _ai_dto(
        content="",  # action в основном
        action_type="show_masters",
        action_data={
            "explanation": "Подходят:",
            "masters": [
                {"master": {"id": 42, "name": "Анна",
                            "specialization": "массаж", "services_preview": []},
                 "match_score": 90, "match_reasons": []},
            ],
        },
    )
    with patch("maxbot.handlers.ai_assistant.ai_concierge.send_message",
               AsyncMock(return_value=dto)):
        await on_free_text(event, ctx)

    assert event.bot.send_message.await_count == 1
    call = event.bot.send_message.await_args.kwargs
    # Текст содержит имена мастеров
    assert "Анна" in call["text"]
    # В attachments есть и card-keyboard, и main_menu (>=2)
    assert len(call["attachments"]) >= 2


@pytest.mark.asyncio
async def test_free_text_confirm_booking_action_renders_yes_no():
    from maxbot.handlers.ai_assistant import on_free_text

    event = _make_text_message(user_id=20005)
    ctx = MemoryContext(chat_id=100, user_id=20005)

    dto = _ai_dto(
        content="",
        action_type="confirm_booking",
        action_data={
            "master_id": 1, "service_id": 1,
            "datetime": "2026-04-30T14:00:00+03:00",
            "master_name": "Анна", "service_name": "Массаж спины",
        },
    )
    with patch("maxbot.handlers.ai_assistant.ai_concierge.send_message",
               AsyncMock(return_value=dto)):
        await on_free_text(event, ctx)

    call = event.bot.send_message.await_args.kwargs
    assert "Анна" in call["text"]
    # Confirm/cancel buttons присутствуют (через render_action)
    payloads = []
    for att in call["attachments"]:
        if att.type == "inline_keyboard":
            for row in att.payload.buttons:
                for btn in row:
                    if hasattr(btn, "payload") and btn.payload:
                        payloads.append(btn.payload)
    assert any("cb:ai:confirm:" in p for p in payloads)


# ─── giveup detection (without action) ────────────────────────────────────


@pytest.mark.asyncio
async def test_free_text_text_giveup_creates_bot_inquiry():
    """DTO с giveup-текстом и без action → BotInquiry + Telegram alert."""
    from maxbot.handlers.ai_assistant import on_free_text
    from maxbot.llm import LLM_GIVEUP_MESSAGE
    from services_app.models import BotInquiry

    event = _make_text_message(user_id=20006, chat_id=777,
                               text="Какой ваш любимый цвет?")
    ctx = MemoryContext(chat_id=777, user_id=20006)

    dto = _ai_dto(content=LLM_GIVEUP_MESSAGE, action_type=None)
    with patch("maxbot.handlers.ai_assistant.ai_concierge.send_message",
               AsyncMock(return_value=dto)), \
         patch("maxbot.handlers.ai_assistant.send_notification_telegram") as mock_tg:
        await on_free_text(event, ctx)

    inquiries = await sync_to_async(list)(BotInquiry.objects.all())
    assert len(inquiries) == 1
    assert inquiries[0].question == "Какой ваш любимый цвет?"
    mock_tg.assert_called_once()
    # Финальное сообщение клиенту — про менеджера
    final = event.bot.send_message.await_args.kwargs["text"]
    assert "менеджер" in final.lower()


@pytest.mark.asyncio
async def test_free_text_action_with_giveup_form_does_not_create_inquiry():
    """Если есть action_type (например ask_clarification) — НЕ giveup, не создаём BotInquiry.

    Текст может содержать «не знаю» в content для UX, но action — это не сдача.
    """
    from maxbot.handlers.ai_assistant import on_free_text
    from services_app.models import BotInquiry

    event = _make_text_message(user_id=20007, text="что-то странное")
    ctx = MemoryContext(chat_id=100, user_id=20007)

    dto = _ai_dto(
        content="",
        action_type="ask_clarification",
        action_data={"question": "Уточните?", "options": ["A", "B"]},
    )
    with patch("maxbot.handlers.ai_assistant.ai_concierge.send_message",
               AsyncMock(return_value=dto)):
        await on_free_text(event, ctx)

    inquiries = await sync_to_async(list)(BotInquiry.objects.all())
    assert len(inquiries) == 0


# ─── intent-router fast path ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_free_text_greeting_intent_skips_ai_concierge():
    """«Привет» → canned response, ai_concierge.send_message НЕ вызывается."""
    from maxbot.handlers.ai_assistant import on_free_text

    event = _make_text_message(user_id=20008, text="Привет!")
    ctx = MemoryContext(chat_id=100, user_id=20008)

    with patch("maxbot.handlers.ai_assistant.ai_concierge.send_message",
               AsyncMock()) as mock_send:
        await on_free_text(event, ctx)

    mock_send.assert_not_awaited()
    # Ответ ушёл — canned greeting
    final = event.bot.send_message.await_args.kwargs["text"]
    assert "Здравствуйте" in final or "Формула тела" in final


# ─── exception in AI Concierge ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_free_text_ai_concierge_exception_falls_back_to_inquiry():
    """OpenAI down / AI Concierge raises → клиент получает «передам менеджеру»."""
    from maxbot.handlers.ai_assistant import on_free_text
    from services_app.models import BotInquiry

    event = _make_text_message(user_id=20009, chat_id=888, text="вопрос")
    ctx = MemoryContext(chat_id=888, user_id=20009)

    with patch("maxbot.handlers.ai_assistant.ai_concierge.send_message",
               AsyncMock(side_effect=RuntimeError("OpenAI 503"))), \
         patch("maxbot.handlers.ai_assistant.send_notification_telegram"):
        await on_free_text(event, ctx)

    inquiries = await sync_to_async(list)(BotInquiry.objects.all())
    assert len(inquiries) == 1
    final = event.bot.send_message.await_args.kwargs["text"]
    assert "менеджер" in final.lower()


# ─── State management ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_free_text_clears_state_after_answer():
    from maxbot.handlers.ai_assistant import on_free_text
    from maxbot.states import AskStates

    event = _make_text_message(user_id=20010)
    ctx = MemoryContext(chat_id=100, user_id=20010)
    await ctx.set_state(AskStates.awaiting_question)

    dto = _ai_dto(content="ok")
    with patch("maxbot.handlers.ai_assistant.ai_concierge.send_message",
               AsyncMock(return_value=dto)):
        await on_free_text(event, ctx)

    assert await ctx.get_state() is None


# ─── Skip empty / no sender ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_free_text_skips_message_without_sender():
    from maxbot.handlers.ai_assistant import on_free_text
    event = _make_text_message(user_id=20011)
    event.message.sender = None
    ctx = MemoryContext(chat_id=100, user_id=20011)
    await on_free_text(event, ctx)
    event.bot.send_message.assert_not_awaited()
    event.bot.send_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_text_skips_empty_message():
    from maxbot.handlers.ai_assistant import on_free_text
    event = _make_text_message(user_id=20012, text="   ")
    ctx = MemoryContext(chat_id=100, user_id=20012)
    await on_free_text(event, ctx)
    event.bot.send_message.assert_not_awaited()
    event.bot.send_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_text_typing_indicator_survives_send_action_failure():
    """Если send_action упал — AI flow всё равно продолжается."""
    from maxbot.handlers.ai_assistant import on_free_text
    event = _make_text_message(user_id=20013, text="Сколько стоит?")
    event.bot.send_action = AsyncMock(side_effect=RuntimeError("network blip"))
    ctx = MemoryContext(chat_id=100, user_id=20013)

    dto = _ai_dto(content="3000 руб.")
    with patch("maxbot.handlers.ai_assistant.ai_concierge.send_message",
               AsyncMock(return_value=dto)):
        await on_free_text(event, ctx)

    event.bot.send_message.assert_awaited_once()
    assert "3000" in event.bot.send_message.await_args.kwargs["text"]


# ─── Главное меню всё ещё содержит кнопку «Задать вопрос» ─────────────────


def test_main_menu_includes_ask_button():
    from maxbot.keyboards import main_menu_keyboard, PAYLOAD_MENU_ASK
    kb = main_menu_keyboard()
    payloads = [b.payload for row in kb.payload.buttons for b in row]
    assert PAYLOAD_MENU_ASK in payloads
