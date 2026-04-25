"""T-10 RED: handler «Контакты» — читает SiteSettings + кнопки клавиатуры."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from asgiref.sync import sync_to_async
from model_bakery import baker

from maxapi.context.context import MemoryContext

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


def _make_callback(*, chat_id=100, user_id=200, payload="cb:menu:contacts"):
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


@pytest.mark.asyncio
async def test_contacts_reads_from_site_settings():
    from maxbot.handlers.contacts import on_show_contacts
    await amake(
        "services_app.SiteSettings",
        contact_phone="8(8412)39-34-33",
        address="г. Пенза, ул. Пушкина, 45",
        working_hours="9:00-21:00",
    )
    event = _make_callback(user_id=8001)
    ctx = MemoryContext(chat_id=100, user_id=8001)
    await on_show_contacts(event, ctx)
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "8(8412)39-34-33" in text
    assert "Пушкина" in text
    assert "9:00" in text


@pytest.mark.asyncio
async def test_contacts_includes_back_button():
    from maxbot.handlers.contacts import on_show_contacts
    from maxbot.keyboards import PAYLOAD_BACK
    await amake("services_app.SiteSettings", contact_phone="123", address="addr", working_hours="9-21")
    event = _make_callback(user_id=8002)
    ctx = MemoryContext(chat_id=100, user_id=8002)
    await on_show_contacts(event, ctx)
    payloads = [
        getattr(b, "payload", None)
        for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert PAYLOAD_BACK in payloads


@pytest.mark.asyncio
async def test_contacts_includes_clipboard_for_phone():
    """Кнопка «Скопировать телефон» — ClipboardButton с phone в payload."""
    from maxbot.handlers.contacts import on_show_contacts
    await amake("services_app.SiteSettings", contact_phone="88412393433", address="A", working_hours="W")
    event = _make_callback(user_id=8003)
    ctx = MemoryContext(chat_id=100, user_id=8003)
    await on_show_contacts(event, ctx)
    buttons = [
        b
        for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    clipboard_buttons = [b for b in buttons if type(b).__name__ == "ClipboardButton"]
    assert len(clipboard_buttons) == 1
    assert clipboard_buttons[0].payload == "88412393433"


@pytest.mark.asyncio
async def test_contacts_includes_map_link_when_set():
    from maxbot.handlers.contacts import on_show_contacts
    await amake(
        "services_app.SiteSettings",
        contact_phone="X", address="A", working_hours="W",
        yandex_maps_link="https://yandex.ru/maps/?text=test",
    )
    event = _make_callback(user_id=8004)
    ctx = MemoryContext(chat_id=100, user_id=8004)
    await on_show_contacts(event, ctx)
    buttons = [
        b
        for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    link_buttons = [b for b in buttons if type(b).__name__ == "LinkButton"]
    assert any(b.url == "https://yandex.ru/maps/?text=test" for b in link_buttons)


@pytest.mark.asyncio
async def test_contacts_no_map_button_when_link_empty():
    from maxbot.handlers.contacts import on_show_contacts
    await amake(
        "services_app.SiteSettings",
        contact_phone="X", address="A", working_hours="W",
        yandex_maps_link=None, google_maps_link=None,
    )
    event = _make_callback(user_id=8005)
    ctx = MemoryContext(chat_id=100, user_id=8005)
    await on_show_contacts(event, ctx)
    buttons = [
        b
        for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert not any(type(b).__name__ == "LinkButton" for b in buttons)


@pytest.mark.asyncio
async def test_contacts_fallback_when_no_site_settings():
    """SiteSettings.objects.first() == None → дефолтный текст, не падаем."""
    from maxbot.handlers.contacts import on_show_contacts
    event = _make_callback(user_id=8006)
    ctx = MemoryContext(chat_id=100, user_id=8006)
    await on_show_contacts(event, ctx)
    event.bot.send_message.assert_awaited_once()
    text = event.bot.send_message.await_args.kwargs["text"]
    assert text  # непустой


@pytest.mark.asyncio
async def test_contacts_skips_when_message_deleted():
    from maxbot.handlers.contacts import on_show_contacts
    event = _make_callback(user_id=8007)
    event.message = None
    ctx = MemoryContext(chat_id=0, user_id=8007)
    await on_show_contacts(event, ctx)
    event.bot.send_message.assert_not_awaited()
