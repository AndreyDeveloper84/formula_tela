"""T-08 RED: handler "Услуги" (каталог + клик на услугу → FSM awaiting_name)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from asgiref.sync import sync_to_async
from model_bakery import baker

from maxapi.context.context import MemoryContext

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


def _make_callback(*, chat_id=100, user_id=200, first_name="Иван", payload="cb:menu:services"):
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


# ─── on_show_services (cb:menu:services) ────────────────────────────────────

@pytest.mark.asyncio
async def test_show_services_reads_active_from_db():
    """Только Service(is_active=True) попадают в клавиатуру."""
    from maxbot.handlers.services import on_show_services
    from maxbot.keyboards import PAYLOAD_SVC_PREFIX

    s_active = await amake("services_app.Service", name="Спина", slug="spina", is_active=True)
    await amake("services_app.Service", name="Скрытая", slug="hidden", is_active=False)

    event = _make_callback(user_id=6001)
    ctx = MemoryContext(chat_id=100, user_id=6001)
    await on_show_services(event, ctx)

    event.bot.send_message.assert_awaited_once()
    payloads = [
        b.payload for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert f"{PAYLOAD_SVC_PREFIX}{s_active.id}" in payloads
    # inactive не должен попасть
    assert not any(p.startswith(PAYLOAD_SVC_PREFIX) and p != f"{PAYLOAD_SVC_PREFIX}{s_active.id}" for p in payloads)


@pytest.mark.asyncio
async def test_show_services_includes_back_button():
    from maxbot.handlers.services import on_show_services
    from maxbot.keyboards import PAYLOAD_BACK
    await amake("services_app.Service", name="Спина", slug="spina", is_active=True)
    event = _make_callback(user_id=6002)
    ctx = MemoryContext(chat_id=100, user_id=6002)
    await on_show_services(event, ctx)
    payloads = [
        b.payload for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert PAYLOAD_BACK in payloads


@pytest.mark.asyncio
async def test_show_services_when_no_active_services():
    """Нет active услуг → fallback-сообщение + кнопка Назад, не падает."""
    from maxbot.handlers.services import on_show_services
    from maxbot.keyboards import PAYLOAD_BACK
    event = _make_callback(user_id=6003)
    ctx = MemoryContext(chat_id=100, user_id=6003)
    await on_show_services(event, ctx)
    event.bot.send_message.assert_awaited_once()
    text = event.bot.send_message.await_args.kwargs["text"]
    # Должен быть какой-то fallback-текст
    assert text  # непустой
    payloads = [
        b.payload for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert PAYLOAD_BACK in payloads


@pytest.mark.asyncio
async def test_show_services_skips_when_message_deleted():
    from maxbot.handlers.services import on_show_services
    event = _make_callback(user_id=6004)
    event.message = None
    ctx = MemoryContext(chat_id=0, user_id=6004)
    await on_show_services(event, ctx)
    event.bot.send_message.assert_not_awaited()


# ─── on_pick_service (cb:svc:{id}) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_pick_service_sets_fsm_awaiting_name():
    from maxbot.handlers.services import on_pick_service
    from maxbot.states import BookingStates

    svc = await amake("services_app.Service", name="Шея", slug="sheya", is_active=True)
    event = _make_callback(user_id=6005, payload=f"cb:svc:{svc.id}")
    ctx = MemoryContext(chat_id=100, user_id=6005)

    await on_pick_service(event, ctx)

    state = await ctx.get_state()
    assert str(state) == str(BookingStates.awaiting_name)
    data = await ctx.get_data()
    assert data["service_id"] == svc.id


@pytest.mark.asyncio
async def test_pick_service_sends_ask_name_text():
    from maxbot.handlers.services import on_pick_service
    svc = await amake("services_app.Service", name="Спина", slug="spina", is_active=True)
    event = _make_callback(user_id=6006, payload=f"cb:svc:{svc.id}")
    ctx = MemoryContext(chat_id=100, user_id=6006)
    await on_pick_service(event, ctx)
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "обращаться" in text.lower() or "имя" in text.lower()


@pytest.mark.asyncio
async def test_pick_service_appends_to_viewed_context():
    """BotUser.context['services_viewed'] получает slug выбранной услуги."""
    from maxbot.handlers.services import on_pick_service
    from services_app.models import BotUser

    bu = await amake("services_app.BotUser", max_user_id=6007, context={})
    svc = await amake("services_app.Service", name="Лимфо", slug="limfo", is_active=True)
    event = _make_callback(user_id=6007, payload=f"cb:svc:{svc.id}")
    ctx = MemoryContext(chat_id=100, user_id=6007)
    await on_pick_service(event, ctx)
    await sync_to_async(bu.refresh_from_db)()
    assert "limfo" in bu.context.get("services_viewed", [])


@pytest.mark.asyncio
async def test_pick_service_invalid_id_graceful():
    """payload cb:svc:99999 (нет такого id) → handler не падает, шлёт сообщение об ошибке."""
    from maxbot.handlers.services import on_pick_service
    event = _make_callback(user_id=6008, payload="cb:svc:99999")
    ctx = MemoryContext(chat_id=100, user_id=6008)
    await on_pick_service(event, ctx)
    # Не упало, FSM не установлен
    assert await ctx.get_state() is None


@pytest.mark.asyncio
async def test_pick_service_skips_when_message_deleted():
    from maxbot.handlers.services import on_pick_service
    svc = await amake("services_app.Service", name="X", slug="x", is_active=True)
    event = _make_callback(user_id=6009, payload=f"cb:svc:{svc.id}")
    event.message = None
    ctx = MemoryContext(chat_id=0, user_id=6009)
    await on_pick_service(event, ctx)
    event.bot.send_message.assert_not_awaited()
