"""T09: ai_action_service.execute_confirm_booking + cancel_conversation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.core.cache import cache
from model_bakery import baker

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@sync_to_async
def _make_conv_with_confirm_action(
    bot_user, master, service, slot_iso="2026-04-30T14:00:00+03:00",
):
    """Helper: создаёт Conversation + assistant message с confirm_booking action_data."""
    from services_app.models import Conversation, Message
    conv = Conversation.objects.create(bot_user=bot_user, is_active=True)
    Message.objects.create(
        conversation=conv, role=Message.Role.ASSISTANT,
        content="",
        action_type="confirm_booking",
        action_data={
            "master_id": master.id,
            "service_id": service.id,
            "datetime": slot_iso,
            "master_name": master.name,
            "service_name": service.name,
        },
    )
    return conv


# ─── execute_confirm_booking — happy path ─────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_booking_happy_path_creates_yclients_record(_clear_cache):
    from maxbot.ai_action_service import execute_confirm_booking
    from services_app.models import BotUser, BookingRequest, Master, Service

    bu = await sync_to_async(baker.make)(
        BotUser, max_user_id=80100, client_name="Тест", client_phone="+79991234567",
    )
    master = await sync_to_async(baker.make)(
        Master, name="Анна", is_active=True, yclients_staff_id="111",
    )
    service = await sync_to_async(baker.make)(
        Service, name="Массаж", is_active=True,
    )
    from services_app.models import ServiceOption
    await sync_to_async(baker.make)(
        ServiceOption, service=service, yclients_service_id="222", is_active=True,
    )
    conv = await _make_conv_with_confirm_action(bu, master, service)

    # Mock YClients API
    api = MagicMock()
    api.create_booking = MagicMock(return_value={"record_id": "REC_999"})

    with patch("maxbot.ai_action_service.send_notification_telegram"):
        result = await execute_confirm_booking(
            conversation=conv, bot_user=bu, yclients_api=api,
        )

    assert result.success is True
    assert result.yclients_record_id == "REC_999"
    assert result.requires_manual is False
    assert "записал" in result.user_message.lower() or "✅" in result.user_message

    # YClients API вызван с правильными параметрами
    api.create_booking.assert_called_once()
    call_kwargs = api.create_booking.call_args.kwargs
    assert call_kwargs["staff_id"] == 111
    assert call_kwargs["services"] == [222]

    # BookingRequest создан с yclients_record_id в comment
    booking = await sync_to_async(BookingRequest.objects.get)(id=result.booking_request_id)
    assert booking.source == "bot_max"
    assert booking.bot_user_id == bu.pk
    assert "REC_999" in booking.comment

    # Conversation закрыт
    await sync_to_async(conv.refresh_from_db)()
    assert conv.is_active is False


@pytest.mark.asyncio
async def test_confirm_booking_idempotent_double_click(_clear_cache):
    """Повторный клик на confirm → existing booking, без YClients call."""
    from maxbot.ai_action_service import execute_confirm_booking
    from services_app.models import BotUser, BookingRequest, Master, Service

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=80101)
    master = await sync_to_async(baker.make)(Master, name="X", is_active=True,
                                              yclients_staff_id="1")
    service = await sync_to_async(baker.make)(Service, is_active=True)
    from services_app.models import ServiceOption
    await sync_to_async(baker.make)(
        ServiceOption, service=service, yclients_service_id="2", is_active=True,
    )
    conv = await _make_conv_with_confirm_action(bu, master, service)

    api = MagicMock()
    api.create_booking = MagicMock(return_value={"record_id": "REC_001"})

    # Первый клик
    with patch("maxbot.ai_action_service.send_notification_telegram"):
        first = await execute_confirm_booking(
            conversation=conv, bot_user=bu, yclients_api=api,
        )
    # Второй клик
    with patch("maxbot.ai_action_service.send_notification_telegram") as tg2:
        second = await execute_confirm_booking(
            conversation=conv, bot_user=bu, yclients_api=api,
        )

    assert first.booking_request_id == second.booking_request_id
    # YClients вызван один раз (на первом)
    assert api.create_booking.call_count == 1
    # Telegram на втором НЕ шлётся
    tg2.assert_not_called()
    # BookingRequest в БД ровно ОДИН
    count = await sync_to_async(BookingRequest.objects.count)()
    assert count == 1


@pytest.mark.asyncio
async def test_confirm_booking_no_yclients_staff_id_graceful(_clear_cache):
    """Master без yclients_staff_id → BookingRequest создан, requires_manual=True."""
    from maxbot.ai_action_service import execute_confirm_booking
    from services_app.models import BotUser, BookingRequest, Master, Service

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=80102)
    master = await sync_to_async(baker.make)(
        Master, name="БезMappinga", is_active=True, yclients_staff_id="",
    )
    service = await sync_to_async(baker.make)(Service, is_active=True)
    from services_app.models import ServiceOption
    await sync_to_async(baker.make)(
        ServiceOption, service=service, yclients_service_id="2", is_active=True,
    )
    conv = await _make_conv_with_confirm_action(bu, master, service)

    api = MagicMock()  # не должен вызваться

    with patch("maxbot.ai_action_service.send_notification_telegram") as tg:
        result = await execute_confirm_booking(
            conversation=conv, bot_user=bu, yclients_api=api,
        )

    assert result.success is False
    assert result.requires_manual is True
    assert result.yclients_record_id is None
    api.create_booking.assert_not_called()
    # BookingRequest всё равно создан — менеджер увидит и обработает
    booking = await sync_to_async(BookingRequest.objects.get)(id=result.booking_request_id)
    assert "requires_manual" in booking.comment
    # Telegram админу — alert о необходимости ручной обработки
    tg.assert_called_once()
    alert = tg.call_args.args[0]
    assert "РУЧНАЯ" in alert.upper() or "ручн" in alert.lower()


@pytest.mark.asyncio
async def test_confirm_booking_yclients_api_failure_graceful(_clear_cache):
    """YClients API падает → BookingRequest без record_id, requires_manual=True."""
    from maxbot.ai_action_service import execute_confirm_booking
    from services_app.models import BotUser, Master, Service

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=80103)
    master = await sync_to_async(baker.make)(Master, name="X", is_active=True,
                                              yclients_staff_id="111")
    service = await sync_to_async(baker.make)(Service, is_active=True)
    from services_app.models import ServiceOption
    await sync_to_async(baker.make)(
        ServiceOption, service=service, yclients_service_id="222", is_active=True,
    )
    conv = await _make_conv_with_confirm_action(bu, master, service)

    api = MagicMock()
    api.create_booking = MagicMock(side_effect=RuntimeError("YClients 503"))

    with patch("maxbot.ai_action_service.send_notification_telegram"):
        result = await execute_confirm_booking(
            conversation=conv, bot_user=bu, yclients_api=api,
        )

    assert result.success is False
    assert result.requires_manual is True
    assert result.booking_request_id is not None  # BookingRequest всё же создан


@pytest.mark.asyncio
async def test_confirm_booking_no_action_data_returns_error(_clear_cache):
    """Conversation без confirm_booking action_data → fallback message."""
    from maxbot.ai_action_service import execute_confirm_booking
    from services_app.models import BotUser, Conversation

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=80104)
    conv = await sync_to_async(Conversation.objects.create)(bot_user=bu, is_active=True)

    result = await execute_confirm_booking(conversation=conv, bot_user=bu)
    assert result.success is False
    assert result.error_code == "no_action_data"


# ─── cancel_conversation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_conversation_closes_and_returns_message():
    from maxbot.ai_action_service import cancel_conversation
    from services_app.models import BotUser, Conversation, Message

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=80110)
    conv = await sync_to_async(Conversation.objects.create)(bot_user=bu, is_active=True)
    msg = await cancel_conversation(conv)
    await sync_to_async(conv.refresh_from_db)()
    assert conv.is_active is False
    assert msg
    # Tool-message сохранён для аудита
    tool_msgs = await sync_to_async(list)(
        Message.objects.filter(conversation=conv, role=Message.Role.TOOL)
    )
    assert len(tool_msgs) == 1


# ─── Phase 1: Conversation.outcome setters ────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_booking_sets_outcome_success_on_yclients_ok(_clear_cache):
    """YClients-record создан → conversation.outcome=success."""
    from maxbot.ai_action_service import execute_confirm_booking
    from services_app.models import BotUser, Conversation, Master, Service

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=80120)
    master = await sync_to_async(baker.make)(
        Master, name="X", is_active=True, yclients_staff_id="1",
    )
    service = await sync_to_async(baker.make)(Service, is_active=True)
    from services_app.models import ServiceOption
    await sync_to_async(baker.make)(
        ServiceOption, service=service, yclients_service_id="2", is_active=True,
    )
    conv = await _make_conv_with_confirm_action(bu, master, service)

    api = MagicMock()
    api.create_booking = MagicMock(return_value={"record_id": "REC_OK"})

    with patch("maxbot.ai_action_service.send_notification_telegram"):
        await execute_confirm_booking(conversation=conv, bot_user=bu, yclients_api=api)

    await sync_to_async(conv.refresh_from_db)()
    assert conv.outcome == Conversation.Outcome.SUCCESS.value
    assert conv.is_active is False


@pytest.mark.asyncio
async def test_confirm_booking_sets_outcome_redirected_on_no_mapping(_clear_cache):
    """Master без yclients_staff_id → outcome=redirected (менеджер запишет вручную)."""
    from maxbot.ai_action_service import execute_confirm_booking
    from services_app.models import BotUser, Conversation, Master, Service

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=80121)
    master = await sync_to_async(baker.make)(
        Master, name="X", is_active=True, yclients_staff_id="",  # Нет mapping
    )
    service = await sync_to_async(baker.make)(Service, is_active=True)
    conv = await _make_conv_with_confirm_action(bu, master, service)

    api = MagicMock()

    with patch("maxbot.ai_action_service.send_notification_telegram"):
        await execute_confirm_booking(conversation=conv, bot_user=bu, yclients_api=api)

    await sync_to_async(conv.refresh_from_db)()
    assert conv.outcome == Conversation.Outcome.REDIRECTED.value
    assert conv.is_active is False


@pytest.mark.asyncio
async def test_cancel_conversation_sets_outcome_abandoned():
    """Кнопка [❌ Отмена] → outcome=abandoned."""
    from maxbot.ai_action_service import cancel_conversation
    from services_app.models import BotUser, Conversation

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=80122)
    conv = await sync_to_async(Conversation.objects.create)(bot_user=bu, is_active=True)
    await cancel_conversation(conv)
    await sync_to_async(conv.refresh_from_db)()
    assert conv.outcome == Conversation.Outcome.ABANDONED.value
