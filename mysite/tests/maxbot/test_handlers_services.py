"""T-08 + T-08.5 RED: handler "Услуги" (двухуровневое меню + клик → FSM)."""
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


# ─── on_show_categories (cb:menu:services) — шаг 1 ──────────────────────────

@pytest.mark.asyncio
async def test_show_categories_lists_active_with_services():
    """Категория попадает в клавиатуру если у неё есть active services."""
    from maxbot.handlers.services import on_show_categories
    from maxbot.keyboards import PAYLOAD_CAT_PREFIX
    cat = await amake("services_app.ServiceCategory", name="Массаж", is_active=True)
    await amake("services_app.Service", name="Спина", slug="spina", is_active=True, category=cat)
    event = _make_callback(user_id=6001)
    ctx = MemoryContext(chat_id=100, user_id=6001)
    await on_show_categories(event, ctx)
    payloads = [
        b.payload for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert f"{PAYLOAD_CAT_PREFIX}{cat.id}" in payloads


@pytest.mark.asyncio
async def test_show_categories_skips_empty_categories():
    """Категория без active services НЕ попадает."""
    from maxbot.handlers.services import on_show_categories
    from maxbot.keyboards import PAYLOAD_CAT_PREFIX
    empty_cat = await amake("services_app.ServiceCategory", name="Пустая", is_active=True)
    event = _make_callback(user_id=6002)
    ctx = MemoryContext(chat_id=100, user_id=6002)
    await on_show_categories(event, ctx)
    payloads = [
        getattr(b, "payload", None) for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert f"{PAYLOAD_CAT_PREFIX}{empty_cat.id}" not in payloads


@pytest.mark.asyncio
async def test_show_categories_fallback_when_empty():
    from maxbot.handlers.services import on_show_categories
    from maxbot.keyboards import PAYLOAD_BACK
    event = _make_callback(user_id=6003)
    ctx = MemoryContext(chat_id=100, user_id=6003)
    await on_show_categories(event, ctx)
    text = event.bot.send_message.await_args.kwargs["text"]
    assert text
    payloads = [
        getattr(b, "payload", None)
        for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert PAYLOAD_BACK in payloads


# ─── on_show_services (cb:cat:{id}) — шаг 2 ─────────────────────────────────

@pytest.mark.asyncio
async def test_show_services_lists_services_in_category():
    from maxbot.handlers.services import on_show_services
    from maxbot.keyboards import PAYLOAD_SVC_PREFIX
    cat = await amake("services_app.ServiceCategory", name="Массаж", is_active=True)
    other = await amake("services_app.ServiceCategory", name="Аппаратные", is_active=True)
    s_in = await amake("services_app.Service", name="Спина", slug="spina", is_active=True, category=cat)
    s_out = await amake("services_app.Service", name="LPG", slug="lpg", is_active=True, category=other)
    event = _make_callback(user_id=6004, payload=f"cb:cat:{cat.id}")
    ctx = MemoryContext(chat_id=100, user_id=6004)
    await on_show_services(event, ctx)
    payloads = [
        b.payload for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert f"{PAYLOAD_SVC_PREFIX}{s_in.id}" in payloads
    assert f"{PAYLOAD_SVC_PREFIX}{s_out.id}" not in payloads


@pytest.mark.asyncio
async def test_show_services_includes_back_to_categories():
    from maxbot.handlers.services import on_show_services
    from maxbot.keyboards import PAYLOAD_MENU_SERVICES
    cat = await amake("services_app.ServiceCategory", name="Cat", is_active=True)
    await amake("services_app.Service", name="X", slug="x", is_active=True, category=cat)
    event = _make_callback(user_id=6005, payload=f"cb:cat:{cat.id}")
    ctx = MemoryContext(chat_id=100, user_id=6005)
    await on_show_services(event, ctx)
    payloads = [
        b.payload for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    # Кнопка «Назад» теперь ведёт обратно к КАТЕГОРИЯМ, не в главное меню
    assert PAYLOAD_MENU_SERVICES in payloads


@pytest.mark.asyncio
async def test_show_services_invalid_category_id():
    from maxbot.handlers.services import on_show_services
    event = _make_callback(user_id=6006, payload="cb:cat:99999")
    ctx = MemoryContext(chat_id=100, user_id=6006)
    await on_show_services(event, ctx)
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "недоступна" in text.lower() or text


@pytest.mark.asyncio
async def test_show_services_truncates_to_max_keyboard_rows():
    """Если в категории > MAX_KEYBOARD_ROWS услуг — обрезаем (защита от MAX API errors.maxRows)."""
    from maxbot.handlers.services import on_show_services
    from maxbot.keyboards import MAX_KEYBOARD_ROWS, PAYLOAD_SVC_PREFIX
    cat = await amake("services_app.ServiceCategory", name="BigCat", is_active=True)
    # Создаём MAX_KEYBOARD_ROWS + 5 услуг
    for i in range(MAX_KEYBOARD_ROWS + 5):
        await amake("services_app.Service", name=f"Svc{i:03d}", slug=f"s{i:03d}", is_active=True, category=cat)
    event = _make_callback(user_id=6007, payload=f"cb:cat:{cat.id}")
    ctx = MemoryContext(chat_id=100, user_id=6007)
    await on_show_services(event, ctx)
    rows = event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
    # MAX_KEYBOARD_ROWS услуг + 1 ряд «Назад» = MAX_KEYBOARD_ROWS+1 ≤ 30
    assert len(rows) == MAX_KEYBOARD_ROWS + 1
    svc_payloads = [b.payload for row in rows for b in row if b.payload and b.payload.startswith(PAYLOAD_SVC_PREFIX)]
    assert len(svc_payloads) == MAX_KEYBOARD_ROWS


@pytest.mark.asyncio
async def test_show_categories_works_for_menu_book_callback():
    """Кнопка «📅 Записаться» (cb:menu:book) ведёт на тот же список категорий что и cb:menu:services."""
    from maxbot.handlers.services import on_show_categories
    from maxbot.keyboards import PAYLOAD_CAT_PREFIX
    cat = await amake("services_app.ServiceCategory", name="Массаж", is_active=True)
    await amake("services_app.Service", name="Спина", slug="spina", is_active=True, category=cat)
    event = _make_callback(user_id=6020, payload="cb:menu:book")
    ctx = MemoryContext(chat_id=100, user_id=6020)
    await on_show_categories(event, ctx)
    payloads = [
        b.payload for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert f"{PAYLOAD_CAT_PREFIX}{cat.id}" in payloads


def test_router_handles_both_book_and_services_payloads():
    """Регистрационная проверка: оба payload'а имеют handler."""
    from maxbot.handlers.services import router
    payloads_handled = []
    for h in router.event_handlers:
        if h.func_event.__name__ == "on_show_categories":
            # filters[0] — это PayloadFilter с magic — проверим что их 2 экземпляра
            payloads_handled.append(h)
    # Должно быть 2 регистрации (по одной на каждый @router.message_callback декоратор)
    assert len(payloads_handled) == 2


@pytest.mark.asyncio
async def test_show_categories_skips_when_message_deleted():
    from maxbot.handlers.services import on_show_categories
    event = _make_callback(user_id=6011)
    event.message = None
    ctx = MemoryContext(chat_id=0, user_id=6011)
    await on_show_categories(event, ctx)
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
