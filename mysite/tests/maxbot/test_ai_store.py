"""DRF-243.2: BotConversationStore — Django-ORM реализация ConversationStore."""
from __future__ import annotations

import pytest
from model_bakery import baker

from maxbot.ai_store import BotConversationStore
from services_app.models import BotUser, Conversation, Message

pytestmark = pytest.mark.django_db


def test_resolve_creates_new_when_none_active():
    bu = baker.make(BotUser, max_user_id=80001)
    store = BotConversationStore()

    conv = store.resolve_active_conversation(bu)

    assert conv.bot_user_id == bu.pk
    assert conv.is_active is True
    assert Conversation.objects.filter(bot_user=bu).count() == 1


def test_resolve_reuses_existing_active():
    bu = baker.make(BotUser, max_user_id=80002)
    existing = Conversation.objects.create(bot_user=bu, is_active=True)
    store = BotConversationStore()

    conv = store.resolve_active_conversation(bu)

    assert conv.id == existing.id
    assert Conversation.objects.filter(bot_user=bu).count() == 1


def test_resolve_skips_closed_creates_new():
    bu = baker.make(BotUser, max_user_id=80003)
    closed = Conversation.objects.create(bot_user=bu, is_active=False)
    store = BotConversationStore()

    conv = store.resolve_active_conversation(bu)

    assert conv.id != closed.id
    assert conv.is_active is True


def test_save_user_message_minimal_fields():
    bu = baker.make(BotUser, max_user_id=80010)
    conv = Conversation.objects.create(bot_user=bu)
    store = BotConversationStore()

    msg = store.save_message(conv, role=Message.Role.USER, content="Привет")

    assert msg.role == "user"
    assert msg.content == "Привет"
    assert msg.action_type == ""
    assert msg.action_data is None
    assert msg.tokens_in == 0
    assert msg.latency_ms is None


def test_save_assistant_message_updates_last_message_at_and_telemetry():
    bu = baker.make(BotUser, max_user_id=80011)
    conv = Conversation.objects.create(bot_user=bu, last_message_at=None)
    store = BotConversationStore()

    msg = store.save_message(
        conv,
        role=Message.Role.ASSISTANT,
        content="Я нашёл вам:",
        action_type="show_masters",
        action_data={"masters": [1, 2]},
        tool_call={"id": "call_1", "name": "show_masters", "arguments": "{}"},
        tool_call_id="call_1",
        tokens_in=120,
        tokens_out=45,
        latency_ms=2300,
    )

    assert msg.action_type == "show_masters"
    assert msg.action_data == {"masters": [1, 2]}
    assert msg.tool_call_id == "call_1"
    assert msg.tokens_in == 120 and msg.tokens_out == 45
    assert msg.latency_ms == 2300

    conv.refresh_from_db()
    assert conv.last_message_at == msg.created_at


def test_load_recent_history_chronological_excludes_id_respects_limit():
    bu = baker.make(BotUser, max_user_id=80020)
    conv = Conversation.objects.create(bot_user=bu)
    store = BotConversationStore()

    # 12 messages — order_by("created_at") даёт m0..m11
    msgs = [
        Message.objects.create(
            conversation=conv,
            role=Message.Role.USER if i % 2 == 0 else Message.Role.ASSISTANT,
            content=f"m{i}",
        )
        for i in range(12)
    ]

    # exclude последнего, limit=5 — должны вернуться m6..m10 (chronological ASC)
    history = store.load_recent_history(conv, exclude_id=msgs[-1].id, limit=5)

    assert [m.content for m in history] == ["m6", "m7", "m8", "m9", "m10"]
