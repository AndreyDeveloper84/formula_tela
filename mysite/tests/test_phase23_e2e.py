"""T11 E2E integration tests — Phase 2.3 AI Concierge full pipeline.

5 сценария сквозного тестирования:
1. Happy-path: execute_confirm_booking → YClients success → outcome=success
2. Partial request → LLM emits ask_clarification → action_type сохранён в Message
3. show_slots + YClients возвращает [] → action_data['slots'] == []
4. YClients API down при confirm → graceful degradation, outcome=redirected
5. Cancellation → outcome=abandoned, tool Message в БД
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from model_bakery import baker

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


# ─── Setup helpers ─────────────────────────────────────────────────────────


@sync_to_async
def _setup_yclients_master_service():
    """Master + Service + ServiceOption с заполненными YClients mapping."""
    from services_app.models import Master, Service, ServiceOption
    service = baker.make(
        Service, is_active=True, name="Лимфодренажный массаж", price_from=2500,
    )
    baker.make(ServiceOption, service=service, yclients_service_id="333",
               price=2500, order=0)
    master = baker.make(
        Master, is_active=True, name="Светлана Орлова", yclients_staff_id="777",
    )
    master.services.add(service)
    return master, service


@sync_to_async
def _make_conv_with_confirm(bot_user, master, service,
                            slot_iso="2026-05-15T10:00:00"):
    """Conversation + assistant Message с action_type=confirm_booking."""
    from services_app.models import Conversation, Message
    conv = Conversation.objects.create(bot_user=bot_user, is_active=True)
    action_data = {
        "master_id": master.id,
        "service_id": service.id,
        "datetime": slot_iso,
        "master_name": master.name,
        "service_name": service.name,
        "price_from": 2500,
    }
    msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.ASSISTANT,
        action_type="confirm_booking",
        action_data=action_data,
        content="",
    )
    conv.last_message_at = msg.created_at
    conv.save(update_fields=["last_message_at"])
    return conv


@sync_to_async
def _get_messages(conv, role=None):
    from services_app.models import Message
    qs = Message.objects.filter(conversation=conv)
    if role:
        qs = qs.filter(role=role)
    return list(qs.order_by("created_at"))


# ─── OpenAI mock builders ──────────────────────────────────────────────────


def _mock_completion(content: str = "", tool_calls=None,
                     tokens_in: int = 80, tokens_out: int = 40):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = msg
    usage = MagicMock()
    usage.prompt_tokens = tokens_in
    usage.completion_tokens = tokens_out
    completion = MagicMock()
    completion.choices = [choice]
    completion.usage = usage
    return completion


def _tc(name: str, args: dict):
    """Create mock tool_call."""
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    tc.id = f"call_{name}"
    return tc


def _openai(completion):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=completion)
    return client


# ─── Scenario 1: Happy-path confirm booking ────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_confirm_booking_happy_path():
    """execute_confirm_booking: YClients returns record_id → success + outcome=success."""
    from maxbot.ai_action_service import execute_confirm_booking
    from services_app.models import BookingRequest, BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=92001,
                     client_name="Елена Тест", client_phone="+79990001111")
    master, service = await _setup_yclients_master_service()
    conv = await _make_conv_with_confirm(bu, master, service)

    mock_api = MagicMock()
    mock_api.create_booking = MagicMock(return_value={"record_id": "YC-E2E-1"})

    with patch("maxbot.ai_action_service.send_notification_telegram"):
        result = await execute_confirm_booking(
            conversation=conv, bot_user=bu, yclients_api=mock_api,
        )

    assert result.success is True
    assert result.yclients_record_id == "YC-E2E-1"
    assert result.requires_manual is False
    assert result.booking_request_id is not None
    assert "✅" in result.user_message or "Записал" in result.user_message

    # YClients вызван с правильными ID
    call_kw = mock_api.create_booking.call_args.kwargs
    assert call_kw["staff_id"] == 777
    assert call_kw["services"] == [333]
    assert "2026-05-15T10:00" in call_kw["datetime"]

    # BookingRequest создан + source=bot_max
    br = await sync_to_async(BookingRequest.objects.get)(id=result.booking_request_id)
    assert br.source == "bot_max"
    assert br.bot_user_id == bu.pk
    assert "YC-E2E-1" in br.comment

    # Conversation закрыта с outcome=success
    conv_db = await sync_to_async(Conversation.objects.get)(id=conv.id)
    assert conv_db.is_active is False
    assert conv_db.outcome == "success"

    # Tool-message создан для audit trail
    msgs = await _get_messages(conv, role=Message.Role.TOOL)
    assert len(msgs) == 1
    assert "YC-E2E-1" in msgs[0].content


# ─── Scenario 2: Partial request → ask_clarification ──────────────────────


@pytest.mark.asyncio
async def test_e2e_partial_request_ask_clarification():
    """Vague user intent → LLM emits ask_clarification → saved in DB, DTO correct."""
    from maxbot.ai_concierge import send_message
    from services_app.models import BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=92002)

    tc = _tc("ask_clarification", {
        "question": "Что именно вас интересует?",
        "options": ["Массаж", "Обёртывания", "LPG"],
    })
    completion = _mock_completion(content="", tool_calls=[tc])
    openai_client = _openai(completion)

    dto = await send_message(
        bot_user=bu, message_text="хочу что-нибудь для тела",
        openai_client=openai_client,
    )

    # DTO корректный
    assert dto.action_type == "ask_clarification"
    assert "Что именно" in dto.action_data["question"]
    assert len(dto.action_data["options"]) == 3

    # Оба Message сохранены в Conversation
    conv = await sync_to_async(Conversation.objects.get)(id=dto.conversation_id)
    all_msgs = await _get_messages(conv)
    assert len(all_msgs) == 2
    user_msg = next(m for m in all_msgs if m.role == "user")
    asst_msg = next(m for m in all_msgs if m.role == "assistant")
    assert user_msg.content == "хочу что-нибудь для тела"
    assert asst_msg.action_type == "ask_clarification"
    assert asst_msg.action_data["options"] == ["Массаж", "Обёртывания", "LPG"]


# ─── Scenario 3: show_slots + empty YClients availability ─────────────────


@pytest.mark.asyncio
async def test_e2e_show_slots_empty_when_fully_booked():
    """YClients возвращает [] слотов → action_data['slots']=[], master_name обогащён."""
    from maxbot.ai_concierge import send_message
    from services_app.models import BotUser

    bu = await amake(BotUser, max_user_id=92003)
    master, service = await _setup_yclients_master_service()

    tc = _tc("show_slots", {
        "master_id": master.id,
        "service_id": service.id,
        "date": "2026-05-16",
        "explanation": "проверяем доступность",
    })
    completion = _mock_completion(content="", tool_calls=[tc])
    openai_client = _openai(completion)

    mock_api = MagicMock()
    mock_api.get_available_times = MagicMock(return_value=[])

    with patch("services_app.yclients_api.get_yclients_api", return_value=mock_api):
        dto = await send_message(
            bot_user=bu,
            message_text="запиши меня на 16 мая к Светлане",
            openai_client=openai_client,
        )

    assert dto.action_type == "show_slots"
    assert dto.action_data["slots"] == []
    assert dto.action_data["master_name"] == master.name
    assert dto.action_data["service_name"] == service.name
    # master_id + date сохранены для _pick_slot_to_confirm (если слоты вдруг найдутся)
    assert dto.action_data["master_id"] == master.id
    assert dto.action_data["date"] == "2026-05-16"


# ─── Scenario 4: YClients API down → graceful degradation ─────────────────


@pytest.mark.asyncio
async def test_e2e_yclients_api_down_graceful():
    """create_booking бросает exception → requires_manual=True, outcome=redirected."""
    from maxbot.ai_action_service import execute_confirm_booking
    from services_app.models import BookingRequest, BotUser, Conversation

    bu = await amake(BotUser, max_user_id=92004,
                     client_name="Ирина", client_phone="+79998887766")
    master, service = await _setup_yclients_master_service()
    conv = await _make_conv_with_confirm(bu, master, service)

    mock_api = MagicMock()
    mock_api.create_booking = MagicMock(
        side_effect=ConnectionError("YClients 503")
    )

    with patch("maxbot.ai_action_service.send_notification_telegram"):
        result = await execute_confirm_booking(
            conversation=conv, bot_user=bu, yclients_api=mock_api,
        )

    assert result.success is False
    assert result.requires_manual is True
    assert result.yclients_record_id is None
    assert result.booking_request_id is not None
    assert "Менеджер" in result.user_message

    # BookingRequest создан (для видимости в admin + ручной записи)
    br = await sync_to_async(BookingRequest.objects.get)(id=result.booking_request_id)
    assert br.source == "bot_max"
    assert "NONE" in br.comment  # yclients_record_id=NONE маркер

    # Conversation закрыта с outcome=redirected (менеджер запишет вручную)
    conv_db = await sync_to_async(Conversation.objects.get)(id=conv.id)
    assert conv_db.is_active is False
    assert conv_db.outcome == "redirected"


# ─── Scenario 5: Cancellation flow ────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_cancel_conversation_abandoned():
    """Клиент нажал «Отмена» → outcome=abandoned, tool-message в БД."""
    from maxbot.ai_action_service import cancel_conversation
    from services_app.models import BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=92005)
    master, service = await _setup_yclients_master_service()
    conv = await _make_conv_with_confirm(bu, master, service)

    msg_text = await cancel_conversation(conv)

    assert "Отмен" in msg_text  # «Отменено. Если передумаете — я тут!»

    # Conversation закрыта с outcome=abandoned
    conv_db = await sync_to_async(Conversation.objects.get)(id=conv.id)
    assert conv_db.is_active is False
    assert conv_db.outcome == "abandoned"

    # Tool-message создан для audit trail
    msgs = await _get_messages(conv, role=Message.Role.TOOL)
    assert len(msgs) == 1
    assert "cancelled" in msgs[0].content
