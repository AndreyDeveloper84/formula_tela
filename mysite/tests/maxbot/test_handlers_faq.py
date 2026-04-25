"""T-11 RED: handler FAQ — список + ответ из HelpArticle."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from asgiref.sync import sync_to_async
from model_bakery import baker

from maxapi.context.context import MemoryContext

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


def _make_callback(*, chat_id=100, user_id=200, payload="cb:menu:faq"):
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


# ─── on_show_faq ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_faq_list_shows_only_active():
    from maxbot.handlers.faq import on_show_faq
    a1 = await amake("services_app.HelpArticle", question="Как записаться?", answer="A1", is_active=True, order=1)
    await amake("services_app.HelpArticle", question="Скрытое", answer="?", is_active=False, order=2)
    event = _make_callback(user_id=9001)
    ctx = MemoryContext(chat_id=100, user_id=9001)
    await on_show_faq(event, ctx)
    payloads = [
        getattr(b, "payload", None)
        for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert f"cb:faq:{a1.id}" in payloads
    # Скрытое — не должно быть
    inactive_payloads = [p for p in payloads if p and p.startswith("cb:faq:") and p != f"cb:faq:{a1.id}"]
    assert inactive_payloads == []


@pytest.mark.asyncio
async def test_faq_list_respects_order():
    from maxbot.handlers.faq import on_show_faq
    a3 = await amake("services_app.HelpArticle", question="Q3", answer="A", is_active=True, order=3)
    a1 = await amake("services_app.HelpArticle", question="Q1", answer="A", is_active=True, order=1)
    a2 = await amake("services_app.HelpArticle", question="Q2", answer="A", is_active=True, order=2)
    event = _make_callback(user_id=9002)
    ctx = MemoryContext(chat_id=100, user_id=9002)
    await on_show_faq(event, ctx)
    payloads = [
        b.payload
        for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
        if b.payload and b.payload.startswith("cb:faq:")
    ]
    assert payloads == [f"cb:faq:{a1.id}", f"cb:faq:{a2.id}", f"cb:faq:{a3.id}"]


@pytest.mark.asyncio
async def test_faq_list_truncates_to_max_keyboard_rows():
    """>29 active HelpArticle → клавиатура обрезана (MAX errors.maxRows)."""
    from maxbot.handlers.faq import on_show_faq
    from maxbot.keyboards import MAX_KEYBOARD_ROWS, PAYLOAD_FAQ_PREFIX
    for i in range(MAX_KEYBOARD_ROWS + 5):
        await amake("services_app.HelpArticle", question=f"Q{i:03d}?", answer="A", is_active=True, order=i)
    event = _make_callback(user_id=9099)
    ctx = MemoryContext(chat_id=100, user_id=9099)
    await on_show_faq(event, ctx)
    rows = event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
    # MAX_KEYBOARD_ROWS faq + 1 «Назад» = MAX_KEYBOARD_ROWS+1 ≤ 30
    assert len(rows) == MAX_KEYBOARD_ROWS + 1
    faq_payloads = [b.payload for row in rows for b in row if b.payload and b.payload.startswith(PAYLOAD_FAQ_PREFIX)]
    assert len(faq_payloads) == MAX_KEYBOARD_ROWS


@pytest.mark.asyncio
async def test_faq_long_question_text_truncated_to_64():
    """MAX лимит text кнопки 64 chars — длинные question обрезаются с многоточием."""
    from maxbot.handlers.faq import on_show_faq
    long_q = "Очень-очень длинный вопрос про массаж который точно не влезет в 64 символа никак?"
    a = await amake("services_app.HelpArticle", question=long_q, answer="A", is_active=True)
    event = _make_callback(user_id=9098)
    ctx = MemoryContext(chat_id=100, user_id=9098)
    await on_show_faq(event, ctx)
    texts = [
        b.text
        for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    # Какая-то из кнопок — обрезанный вариант ≤64 chars
    long_button = next((t for t in texts if "длинный" in t), None)
    assert long_button is not None
    assert len(long_button) <= 64


@pytest.mark.asyncio
async def test_faq_list_empty_fallback():
    from maxbot.handlers.faq import on_show_faq
    event = _make_callback(user_id=9003)
    ctx = MemoryContext(chat_id=100, user_id=9003)
    await on_show_faq(event, ctx)
    event.bot.send_message.assert_awaited_once()
    text = event.bot.send_message.await_args.kwargs["text"]
    assert text  # непустой


# ─── on_show_faq_answer ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_faq_answer_returns_text():
    from maxbot.handlers.faq import on_show_faq_answer
    a = await amake("services_app.HelpArticle", question="Q", answer="Очень полезный ответ", is_active=True)
    event = _make_callback(user_id=9004, payload=f"cb:faq:{a.id}")
    ctx = MemoryContext(chat_id=100, user_id=9004)
    await on_show_faq_answer(event, ctx)
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "Очень полезный ответ" in text


@pytest.mark.asyncio
async def test_faq_answer_appends_to_viewed_context():
    from maxbot.handlers.faq import on_show_faq_answer
    from services_app.models import BotUser
    bu = await amake("services_app.BotUser", max_user_id=9005, context={})
    a = await amake("services_app.HelpArticle", question="Q", answer="A", is_active=True)
    event = _make_callback(user_id=9005, payload=f"cb:faq:{a.id}")
    ctx = MemoryContext(chat_id=100, user_id=9005)
    await on_show_faq_answer(event, ctx)
    bu_refreshed = await BotUser.objects.aget(pk=bu.id)
    assert a.id in bu_refreshed.context.get("faqs_viewed", [])


@pytest.mark.asyncio
async def test_faq_answer_invalid_id_graceful():
    from maxbot.handlers.faq import on_show_faq_answer
    event = _make_callback(user_id=9006, payload="cb:faq:99999")
    ctx = MemoryContext(chat_id=100, user_id=9006)
    await on_show_faq_answer(event, ctx)
    # Не упало, fallback-сообщение отправлено
    event.bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_faq_answer_skips_inactive():
    from maxbot.handlers.faq import on_show_faq_answer
    a = await amake("services_app.HelpArticle", question="Q", answer="A", is_active=False)
    event = _make_callback(user_id=9007, payload=f"cb:faq:{a.id}")
    ctx = MemoryContext(chat_id=100, user_id=9007)
    await on_show_faq_answer(event, ctx)
    # Inactive → fallback
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "A" not in text  # не сам ответ
