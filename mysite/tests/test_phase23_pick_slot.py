"""Phase 1: on_pick_slot deterministic path — _pick_slot_to_confirm."""
from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from model_bakery import baker

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


@sync_to_async
def _setup_master_service():
    from services_app.models import Master, Service
    service = baker.make(Service, is_active=True, name="Классический массаж", price_from=1500)
    master = baker.make(Master, is_active=True, name="Сазонова Инна")
    master.services.add(service)
    return master, service


@sync_to_async
def _make_show_slots_conv(bot_user, master, service, date_str="2026-04-29"):
    from services_app.models import Conversation, Message
    conv = Conversation.objects.create(bot_user=bot_user, is_active=True)
    Message.objects.create(
        conversation=conv,
        role=Message.Role.ASSISTANT,
        action_type="show_slots",
        action_data={"master_id": master.id, "service_id": service.id, "date": date_str},
        content="",
    )
    return conv


@sync_to_async
def _get_confirm_msg(conv):
    from services_app.models import Message
    return Message.objects.filter(conversation=conv, action_type="confirm_booking").first()


@sync_to_async
def _refresh_conv(conv):
    conv.refresh_from_db()
    return conv


@pytest.mark.asyncio
async def test_pick_slot_to_confirm_returns_action_data():
    """Happy path: show_slots в истории + slot time → confirm_booking action_data."""
    from maxbot.handlers.ai_callbacks import _pick_slot_to_confirm
    from services_app.models import BotUser

    bu = await amake(BotUser, max_user_id=91001)
    master, service = await _setup_master_service()
    conv = await _make_show_slots_conv(bu, master, service)

    result = await _pick_slot_to_confirm(str(conv.id), "18:30")

    assert result is not None, "должен вернуть action_data, а не None"
    assert result["master_id"] == master.id
    assert result["service_id"] == service.id
    assert "2026-04-29T18:30:00" in result["datetime"]
    assert result["master_name"] == master.name
    assert result["service_name"] == service.name


@pytest.mark.asyncio
async def test_pick_slot_to_confirm_saves_confirm_message():
    """Confirm Message сохраняется в conversation и обновляет last_message_at."""
    from maxbot.handlers.ai_callbacks import _pick_slot_to_confirm
    from services_app.models import BotUser

    bu = await amake(BotUser, max_user_id=91002)
    master, service = await _setup_master_service()
    conv = await _make_show_slots_conv(bu, master, service)

    await _pick_slot_to_confirm(str(conv.id), "19:00")

    confirm_msg = await _get_confirm_msg(conv)
    assert confirm_msg is not None, "confirm_booking Message должен быть в DB"
    assert confirm_msg.role == "assistant"
    assert confirm_msg.action_data["master_id"] == master.id

    conv = await _refresh_conv(conv)
    assert conv.last_message_at == confirm_msg.created_at


@pytest.mark.asyncio
async def test_pick_slot_to_confirm_returns_none_when_no_show_slots():
    """Нет show_slots в истории → None (→ LLM fallback)."""
    from maxbot.handlers.ai_callbacks import _pick_slot_to_confirm
    from services_app.models import BotUser, Conversation

    bu = await amake(BotUser, max_user_id=91003)
    conv = await sync_to_async(Conversation.objects.create)(bot_user=bu, is_active=True)

    result = await _pick_slot_to_confirm(str(conv.id), "18:30")

    assert result is None


@pytest.mark.asyncio
async def test_pick_slot_to_confirm_handles_iso_slot_str():
    """slot_str в ISO-формате (с 'T') тоже работает."""
    from maxbot.handlers.ai_callbacks import _pick_slot_to_confirm
    from services_app.models import BotUser

    bu = await amake(BotUser, max_user_id=91004)
    master, service = await _setup_master_service()
    conv = await _make_show_slots_conv(bu, master, service, date_str="2026-04-29")

    result = await _pick_slot_to_confirm(str(conv.id), "2026-04-29T20:00:00")

    assert result is not None
    assert "2026-04-29T20:00:00" in result["datetime"]


@pytest.mark.asyncio
async def test_pick_slot_to_confirm_returns_none_for_closed_conv():
    """Conversation уже закрыт (is_active=False) → None."""
    from maxbot.handlers.ai_callbacks import _pick_slot_to_confirm
    from services_app.models import BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=91005)
    master, service = await _setup_master_service()

    @sync_to_async
    def _make_closed():
        conv = Conversation.objects.create(bot_user=bu, is_active=False)
        Message.objects.create(
            conversation=conv,
            role=Message.Role.ASSISTANT,
            action_type="show_slots",
            action_data={"master_id": master.id, "service_id": service.id, "date": "2026-04-29"},
            content="",
        )
        return conv

    conv = await _make_closed()
    result = await _pick_slot_to_confirm(str(conv.id), "18:30")

    assert result is None
