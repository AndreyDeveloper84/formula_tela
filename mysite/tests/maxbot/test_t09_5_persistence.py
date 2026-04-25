"""T-09.5: persistence client_name/phone в BotUser + skip-FSM при повторной записи."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from asgiref.sync import sync_to_async
from model_bakery import baker

from maxapi.context.context import MemoryContext

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


def _make_callback(*, chat_id=100, user_id=200, payload="cb:menu:services"):
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


# ─── Persistence: confirm_yes сохраняет client_name/phone в BotUser ─────────

@pytest.mark.asyncio
async def test_confirm_yes_persists_client_name_phone_to_bot_user():
    """После успешной записи BotUser.client_name/phone заполняются."""
    from maxbot.handlers.booking import on_confirm_yes
    from maxbot.states import BookingStates
    from services_app.models import BotUser

    svc = await amake("services_app.Service", name="Спина", slug="spina", is_active=True)
    bu = await amake(
        "services_app.BotUser",
        max_user_id=11001,
        client_name="",
        client_phone="",
    )
    event = _make_callback(user_id=11001, payload="cb:confirm:yes")
    ctx = MemoryContext(chat_id=100, user_id=11001)
    await ctx.set_state(BookingStates.awaiting_confirm)
    await ctx.update_data(service_id=svc.id, name="Иван Петров", phone="+79991234567")

    with patch("maxbot.handlers.booking._notify_bot_booking", new=MagicMock()):
        await on_confirm_yes(event, ctx)

    refreshed = await BotUser.objects.aget(pk=bu.id)
    assert refreshed.client_name == "Иван Петров"
    assert refreshed.client_phone == "+79991234567"


# ─── Skip-FSM: pick_service с заполненным BotUser → сразу awaiting_confirm ──

@pytest.mark.asyncio
async def test_pick_service_skips_fsm_when_full_data_known():
    """Если client_name + client_phone в BotUser — пропускаем FSM, сразу awaiting_confirm."""
    from maxbot.handlers.services import on_pick_service
    from maxbot.states import BookingStates

    svc = await amake("services_app.Service", name="Шея", slug="sheya", is_active=True)
    await amake(
        "services_app.BotUser",
        max_user_id=11002,
        client_name="Анна",
        client_phone="+79991111111",
    )
    event = _make_callback(user_id=11002, payload=f"cb:svc:{svc.id}")
    ctx = MemoryContext(chat_id=100, user_id=11002)
    await on_pick_service(event, ctx)

    assert str(await ctx.get_state()) == str(BookingStates.awaiting_confirm)
    data = await ctx.get_data()
    assert data["name"] == "Анна"
    assert data["phone"] == "+79991111111"
    assert data["service_id"] == svc.id


@pytest.mark.asyncio
async def test_pick_service_skip_sends_confirm_keyboard_with_other():
    """В клавиатуре подтверждения должна быть кнопка «Указать другие»."""
    from maxbot.handlers.services import on_pick_service
    from maxbot.keyboards import PAYLOAD_CONFIRM_OTHER, PAYLOAD_CONFIRM_YES

    svc = await amake("services_app.Service", name="X", slug="x", is_active=True)
    await amake(
        "services_app.BotUser",
        max_user_id=11003,
        client_name="Анна",
        client_phone="+79991111111",
    )
    event = _make_callback(user_id=11003, payload=f"cb:svc:{svc.id}")
    ctx = MemoryContext(chat_id=100, user_id=11003)
    await on_pick_service(event, ctx)

    payloads = [
        b.payload
        for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert PAYLOAD_CONFIRM_YES in payloads
    assert PAYLOAD_CONFIRM_OTHER in payloads


@pytest.mark.asyncio
async def test_pick_service_normal_fsm_when_no_client_data():
    """Если в BotUser нет client_name/phone — обычный FSM (awaiting_name)."""
    from maxbot.handlers.services import on_pick_service
    from maxbot.states import BookingStates

    svc = await amake("services_app.Service", name="X", slug="x", is_active=True)
    # Только display_name, без client_*
    await amake(
        "services_app.BotUser",
        max_user_id=11004,
        client_name="",
        client_phone="",
        display_name="Андрей",
    )
    event = _make_callback(user_id=11004, payload=f"cb:svc:{svc.id}")
    ctx = MemoryContext(chat_id=100, user_id=11004)
    await on_pick_service(event, ctx)

    assert str(await ctx.get_state()) == str(BookingStates.awaiting_name)


# ─── Кнопка «Указать другие данные» сбрасывает FSM в awaiting_name ─────────

@pytest.mark.asyncio
async def test_confirm_other_resets_to_awaiting_name():
    from maxbot.handlers.booking import on_confirm_other
    from maxbot.states import BookingStates
    event = _make_callback(user_id=11005, payload="cb:confirm:other")
    ctx = MemoryContext(chat_id=100, user_id=11005)
    await ctx.set_state(BookingStates.awaiting_confirm)
    await ctx.update_data(
        service_id=42, service_name="Спина", name="OldName", phone="+79990000000",
    )
    await on_confirm_other(event, ctx)

    assert str(await ctx.get_state()) == str(BookingStates.awaiting_name)
    data = await ctx.get_data()
    # service_id сохранился, name/phone стёрты
    assert data["service_id"] == 42
    assert "name" not in data
    assert "phone" not in data
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "обращаться" in text.lower()
