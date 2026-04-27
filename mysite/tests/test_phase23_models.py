"""T01 Phase 2.3: Master.yclients_staff_id + Conversation + Message модели."""
from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async
from model_bakery import baker

pytestmark = pytest.mark.django_db


# ─── Master.yclients_staff_id ───────────────────────────────────────────


def test_master_has_yclients_staff_id_field():
    """Поле для маппинга наш Master ↔ YClients staff (для booking API)."""
    from services_app.models import Master
    field = Master._meta.get_field("yclients_staff_id")
    assert field is not None
    assert field.blank is True
    assert field.null is True


def test_master_yclients_staff_id_can_be_set_and_queried():
    from services_app.models import Master
    master = baker.make(Master, name="Анна Иванова", yclients_staff_id="12345")
    fetched = Master.objects.get(pk=master.pk)
    assert fetched.yclients_staff_id == "12345"

    # Лукап по yclients_staff_id (для booking flow)
    found = Master.objects.filter(yclients_staff_id="12345").first()
    assert found is not None
    assert found.pk == master.pk


def test_master_without_yclients_staff_id_is_valid():
    """Поле необязательное — мастер может быть в БД до маппинга."""
    from services_app.models import Master
    master = baker.make(Master, name="Без маппинга", yclients_staff_id=None)
    assert master.pk is not None


# ─── Conversation модель ────────────────────────────────────────────────


def test_conversation_has_uuid_pk_and_bot_user_fk():
    from services_app.models import BotUser, Conversation
    bu = baker.make(BotUser, max_user_id=80001)
    conv = Conversation.objects.create(bot_user=bu)
    assert isinstance(conv.id, uuid.UUID)
    assert conv.bot_user_id == bu.pk


def test_conversation_defaults():
    from services_app.models import BotUser, Conversation
    bu = baker.make(BotUser, max_user_id=80002)
    conv = Conversation.objects.create(bot_user=bu)
    assert conv.is_active is True
    assert conv.deleted_at is None
    assert conv.last_message_at is None
    assert conv.created_at is not None


def test_conversation_can_be_soft_closed():
    """is_active=False + last_message_at для analytics («когда закрылся»)."""
    from django.utils import timezone
    from services_app.models import BotUser, Conversation
    bu = baker.make(BotUser, max_user_id=80003)
    conv = Conversation.objects.create(bot_user=bu)
    now = timezone.now()
    conv.is_active = False
    conv.last_message_at = now
    conv.save()
    fetched = Conversation.objects.get(pk=conv.pk)
    assert fetched.is_active is False
    assert fetched.last_message_at is not None


def test_conversation_cascade_delete_on_bot_user():
    """Если BotUser удалён → Conversation тоже (CASCADE)."""
    from services_app.models import BotUser, Conversation
    bu = baker.make(BotUser, max_user_id=80004)
    Conversation.objects.create(bot_user=bu)
    Conversation.objects.create(bot_user=bu)
    bu_pk = bu.pk
    assert Conversation.objects.filter(bot_user_id=bu_pk).count() == 2
    bu.delete()
    assert Conversation.objects.filter(bot_user_id=bu_pk).count() == 0


def test_conversation_str_includes_id_and_bot_user():
    from services_app.models import BotUser, Conversation
    bu = baker.make(BotUser, max_user_id=80005)
    conv = Conversation.objects.create(bot_user=bu)
    s = str(conv)
    assert str(conv.id)[:8] in s  # short uuid prefix


# ─── Message модель ─────────────────────────────────────────────────────


def test_message_has_role_choices_and_content():
    from services_app.models import BotUser, Conversation, Message
    bu = baker.make(BotUser, max_user_id=80010)
    conv = Conversation.objects.create(bot_user=bu)
    msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.USER,
        content="Привет",
    )
    assert msg.role == "user"
    assert msg.content == "Привет"


def test_message_role_choices_complete():
    from services_app.models import Message
    roles = {r.value for r in Message.Role}
    assert roles == {"user", "assistant", "tool", "system"}


def test_message_action_fields_optional():
    """action_type + action_data — для assistant сообщений с tool-call."""
    from services_app.models import BotUser, Conversation, Message
    bu = baker.make(BotUser, max_user_id=80011)
    conv = Conversation.objects.create(bot_user=bu)
    msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.ASSISTANT,
        content="",
        action_type="show_masters",
        action_data={"masters": [{"id": 42, "name": "Анна"}]},
    )
    assert msg.action_type == "show_masters"
    assert msg.action_data["masters"][0]["id"] == 42


def test_message_telemetry_fields():
    """tokens_in/out + latency_ms — для observability."""
    from services_app.models import BotUser, Conversation, Message
    bu = baker.make(BotUser, max_user_id=80012)
    conv = Conversation.objects.create(bot_user=bu)
    msg = Message.objects.create(
        conversation=conv, role=Message.Role.ASSISTANT, content="ok",
        tokens_in=120, tokens_out=45, latency_ms=2300,
    )
    assert msg.tokens_in == 120
    assert msg.tokens_out == 45
    assert msg.latency_ms == 2300


def test_message_tool_call_fields_optional():
    """tool_call (raw OpenAI object) + tool_call_id — для audit/debug."""
    from services_app.models import BotUser, Conversation, Message
    bu = baker.make(BotUser, max_user_id=80013)
    conv = Conversation.objects.create(bot_user=bu)
    msg = Message.objects.create(
        conversation=conv, role=Message.Role.TOOL, content="result",
        tool_call={"name": "show_masters", "arguments": "{}"},
        tool_call_id="call_abc123",
    )
    assert msg.tool_call["name"] == "show_masters"
    assert msg.tool_call_id == "call_abc123"


def test_message_cascade_delete_on_conversation():
    from services_app.models import BotUser, Conversation, Message
    bu = baker.make(BotUser, max_user_id=80014)
    conv = Conversation.objects.create(bot_user=bu)
    Message.objects.create(conversation=conv, role="user", content="a")
    Message.objects.create(conversation=conv, role="assistant", content="b")
    conv_pk = conv.pk
    assert Message.objects.filter(conversation_id=conv_pk).count() == 2
    conv.delete()
    assert Message.objects.filter(conversation_id=conv_pk).count() == 0


def test_message_ordering_is_chronological():
    """Загружая историю — порядок ASC по created_at."""
    from services_app.models import BotUser, Conversation, Message
    bu = baker.make(BotUser, max_user_id=80015)
    conv = Conversation.objects.create(bot_user=bu)
    m1 = Message.objects.create(conversation=conv, role="user", content="1")
    m2 = Message.objects.create(conversation=conv, role="assistant", content="2")
    m3 = Message.objects.create(conversation=conv, role="user", content="3")
    msgs = list(conv.messages.all())
    assert [m.pk for m in msgs] == [m1.pk, m2.pk, m3.pk]


def test_message_str_short_preview():
    from services_app.models import BotUser, Conversation, Message
    bu = baker.make(BotUser, max_user_id=80016)
    conv = Conversation.objects.create(bot_user=bu)
    msg = Message.objects.create(
        conversation=conv, role="user",
        content="Это длинное сообщение которое должно быть обрезано в строковом представлении модели",
    )
    s = str(msg)
    assert "user" in s
    assert "Это длинное сообщение" in s


# ─── Admin smoke ──────────────────────────────────────────────────────────


def test_conversation_admin_registered():
    from django.contrib import admin
    from services_app.models import Conversation
    assert Conversation in admin.site._registry


def test_message_admin_registered():
    from django.contrib import admin
    from services_app.models import Message
    assert Message in admin.site._registry


def test_master_admin_yclients_staff_id_in_fields():
    """Чтобы менеджер мог заполнить ID через админку."""
    from django.contrib import admin
    from services_app.models import Master
    master_admin = admin.site._registry[Master]
    # fields ИЛИ fieldsets должно содержать yclients_staff_id
    flat_fields = []
    if master_admin.fields:
        flat_fields.extend(master_admin.fields)
    if master_admin.fieldsets:
        for _, opts in master_admin.fieldsets:
            flat_fields.extend(opts.get("fields", []))
    assert "yclients_staff_id" in flat_fields, (
        "Master.yclients_staff_id должен быть редактируемым в /admin/"
    )
