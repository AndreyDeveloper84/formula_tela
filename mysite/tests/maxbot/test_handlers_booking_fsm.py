"""T-09 RED: handler FSM-заявки (awaiting_name → awaiting_phone → awaiting_confirm)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from asgiref.sync import sync_to_async
from model_bakery import baker

from maxapi.context.context import MemoryContext

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


def _make_text_message(*, chat_id=100, user_id=200, first_name="Иван", text="some"):
    sender = MagicMock()
    sender.user_id = user_id
    sender.first_name = first_name
    sender.full_name = first_name
    body = MagicMock()
    body.text = text
    event = MagicMock()
    event.message = MagicMock()
    event.message.sender = sender
    event.message.recipient = MagicMock()
    event.message.recipient.chat_id = chat_id
    event.message.body = body
    event.message.answer = AsyncMock()
    event.bot = MagicMock()
    event.bot.send_message = AsyncMock()
    return event


def _make_callback(*, chat_id=100, user_id=200, first_name="Иван", payload="cb:confirm:yes"):
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


# ─── on_name_input ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_name_input_too_short_rejected():
    from maxbot.handlers.booking import on_name_input
    from maxbot.states import BookingStates
    event = _make_text_message(user_id=7001, text="A")
    ctx = MemoryContext(chat_id=100, user_id=7001)
    await ctx.set_state(BookingStates.awaiting_name)
    await ctx.update_data(service_id=1)
    await on_name_input(event, ctx)
    # Остаёмся в awaiting_name
    assert str(await ctx.get_state()) == str(BookingStates.awaiting_name)
    # Не сохранили name
    data = await ctx.get_data()
    assert "name" not in data
    # Отправили текст с просьбой повторить
    event.bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_name_input_with_digits_rejected():
    from maxbot.handlers.booking import on_name_input
    from maxbot.states import BookingStates
    event = _make_text_message(user_id=7002, text="Иван123")
    ctx = MemoryContext(chat_id=100, user_id=7002)
    await ctx.set_state(BookingStates.awaiting_name)
    await on_name_input(event, ctx)
    assert str(await ctx.get_state()) == str(BookingStates.awaiting_name)


@pytest.mark.asyncio
async def test_name_input_valid_advances_to_awaiting_phone():
    from maxbot.handlers.booking import on_name_input
    from maxbot.states import BookingStates
    event = _make_text_message(user_id=7003, text="Иван Петров")
    ctx = MemoryContext(chat_id=100, user_id=7003)
    await ctx.set_state(BookingStates.awaiting_name)
    await ctx.update_data(service_id=10)
    await on_name_input(event, ctx)
    assert str(await ctx.get_state()) == str(BookingStates.awaiting_phone)
    data = await ctx.get_data()
    assert data["name"] == "Иван Петров"
    assert data["service_id"] == 10  # не потеряли
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "телефон" in text.lower()


# ─── on_phone_input ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_phone_input_normalizes_to_plus7():
    from maxbot.handlers.booking import on_phone_input
    from maxbot.states import BookingStates
    event = _make_text_message(user_id=7004, text="8 (999) 123-45-67")
    ctx = MemoryContext(chat_id=100, user_id=7004)
    await ctx.set_state(BookingStates.awaiting_phone)
    await ctx.update_data(service_id=10, name="Иван")
    await on_phone_input(event, ctx)
    assert str(await ctx.get_state()) == str(BookingStates.awaiting_confirm)
    data = await ctx.get_data()
    assert data["phone"] == "+79991234567"


@pytest.mark.asyncio
async def test_phone_input_rejects_invalid():
    from maxbot.handlers.booking import on_phone_input
    from maxbot.states import BookingStates
    event = _make_text_message(user_id=7005, text="abc")
    ctx = MemoryContext(chat_id=100, user_id=7005)
    await ctx.set_state(BookingStates.awaiting_phone)
    await ctx.update_data(service_id=10, name="Иван")
    await on_phone_input(event, ctx)
    # Остаёмся в awaiting_phone
    assert str(await ctx.get_state()) == str(BookingStates.awaiting_phone)
    data = await ctx.get_data()
    assert "phone" not in data


@pytest.mark.asyncio
async def test_phone_input_sends_confirm_keyboard():
    from maxbot.handlers.booking import on_phone_input
    from maxbot.states import BookingStates
    from maxbot.keyboards import PAYLOAD_CONFIRM_YES
    event = _make_text_message(user_id=7006, text="+79991234567")
    ctx = MemoryContext(chat_id=100, user_id=7006)
    await ctx.set_state(BookingStates.awaiting_phone)
    await ctx.update_data(service_id=10, name="Иван")
    await on_phone_input(event, ctx)
    payloads = [
        b.payload for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert PAYLOAD_CONFIRM_YES in payloads


# ─── on_confirm_yes (cb:confirm:yes) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_yes_creates_booking_request_with_source_bot_max():
    from maxbot.handlers.booking import on_confirm_yes
    from maxbot.states import BookingStates
    from services_app.models import BookingRequest

    svc = await amake("services_app.Service", name="Спина", slug="spina", is_active=True)
    bu = await amake("services_app.BotUser", max_user_id=7007, client_name="", display_name="MAX_Name")

    event = _make_callback(user_id=7007)
    ctx = MemoryContext(chat_id=100, user_id=7007)
    await ctx.set_state(BookingStates.awaiting_confirm)
    await ctx.update_data(service_id=svc.id, name="Иван", phone="+79991234567")

    with patch("maxbot.handlers.booking._notify_bot_booking", new=MagicMock()):
        await on_confirm_yes(event, ctx)

    br = await BookingRequest.objects.aget(client_phone="+79991234567")
    assert br.source == "bot_max"
    assert br.client_name == "Иван"
    assert br.service_name == svc.name
    assert (await sync_to_async(lambda: br.bot_user.id)()) == bu.id


@pytest.mark.asyncio
async def test_confirm_yes_calls_notify():
    from maxbot.handlers.booking import on_confirm_yes
    from maxbot.states import BookingStates
    svc = await amake("services_app.Service", name="X", slug="x", is_active=True)
    await amake("services_app.BotUser", max_user_id=7008)
    event = _make_callback(user_id=7008)
    ctx = MemoryContext(chat_id=100, user_id=7008)
    await ctx.set_state(BookingStates.awaiting_confirm)
    await ctx.update_data(service_id=svc.id, name="Иван", phone="+79991234567")

    with patch("maxbot.handlers.booking._notify_bot_booking") as mock_notify:
        await on_confirm_yes(event, ctx)
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_confirm_yes_clears_state():
    from maxbot.handlers.booking import on_confirm_yes
    from maxbot.states import BookingStates
    svc = await amake("services_app.Service", name="Y", slug="y", is_active=True)
    await amake("services_app.BotUser", max_user_id=7009)
    event = _make_callback(user_id=7009)
    ctx = MemoryContext(chat_id=100, user_id=7009)
    await ctx.set_state(BookingStates.awaiting_confirm)
    await ctx.update_data(service_id=svc.id, name="Иван", phone="+79991234567")
    with patch("maxbot.handlers.booking._notify_bot_booking", new=MagicMock()):
        await on_confirm_yes(event, ctx)
    assert await ctx.get_state() is None


@pytest.mark.asyncio
async def test_confirm_yes_increments_bookings_count_in_context():
    from maxbot.handlers.booking import on_confirm_yes
    from maxbot.states import BookingStates
    from services_app.models import BotUser
    svc = await amake("services_app.Service", name="Z", slug="z", is_active=True)
    bu = await amake("services_app.BotUser", max_user_id=7010, context={})
    event = _make_callback(user_id=7010)
    ctx = MemoryContext(chat_id=100, user_id=7010)
    await ctx.set_state(BookingStates.awaiting_confirm)
    await ctx.update_data(service_id=svc.id, name="Иван", phone="+79991234567")
    with patch("maxbot.handlers.booking._notify_bot_booking", new=MagicMock()):
        await on_confirm_yes(event, ctx)
    bu_refreshed = await BotUser.objects.aget(pk=bu.id)
    assert bu_refreshed.context.get("bookings_count", 0) == 1


# ─── on_confirm_no (cb:confirm:no) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_no_clears_state_without_creating_booking():
    from maxbot.handlers.booking import on_confirm_no
    from maxbot.states import BookingStates
    from services_app.models import BookingRequest
    event = _make_callback(user_id=7011, payload="cb:confirm:no")
    ctx = MemoryContext(chat_id=100, user_id=7011)
    await ctx.set_state(BookingStates.awaiting_confirm)
    await ctx.update_data(service_id=1, name="Test", phone="+79991234567")
    await on_confirm_no(event, ctx)
    assert await ctx.get_state() is None
    # Заявка НЕ создана
    assert await BookingRequest.objects.acount() == 0
