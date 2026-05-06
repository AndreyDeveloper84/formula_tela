"""Phase 3.2B T06: race-condition guards (recent user activity)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from model_bakery import baker

from services_app.models import BotUser, Conversation, Message


pytestmark = pytest.mark.django_db


def _utc(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("UTC"))


def test_no_recent_activity_not_skipped():
    from maxbot.nudges.race_guards import should_skip_due_to_recent_activity
    bot_user = baker.make(BotUser, max_user_id=1)
    blocked, _ = should_skip_due_to_recent_activity(
        bot_user, now=_utc(2026, 5, 5, 12),
    )
    assert blocked is False


def test_user_message_within_5min_skips():
    from maxbot.nudges.race_guards import should_skip_due_to_recent_activity
    bot_user = baker.make(BotUser, max_user_id=2)
    convo = baker.make(Conversation, bot_user=bot_user)
    msg = Message.objects.create(
        conversation=convo, role="user", content="hi",
    )
    # Message.created_at is auto_now_add=True; use .update() to override.
    Message.objects.filter(pk=msg.pk).update(
        created_at=_utc(2026, 5, 5, 11, 58),
    )
    blocked, reason = should_skip_due_to_recent_activity(
        bot_user, now=_utc(2026, 5, 5, 12, 0),
    )
    assert blocked is True
    assert reason == "race_user_message_5min"


def test_conversation_active_within_10min_skips():
    from maxbot.nudges.race_guards import should_skip_due_to_recent_activity
    bot_user = baker.make(BotUser, max_user_id=3)
    baker.make(
        Conversation, bot_user=bot_user,
        last_message_at=_utc(2026, 5, 5, 11, 53),
    )
    blocked, reason = should_skip_due_to_recent_activity(
        bot_user, now=_utc(2026, 5, 5, 12, 0),
    )
    assert blocked is True
    assert reason == "race_conversation_10min"


def test_user_message_older_than_5min_not_skipped():
    from maxbot.nudges.race_guards import should_skip_due_to_recent_activity
    bot_user = baker.make(BotUser, max_user_id=4)
    convo = baker.make(
        Conversation, bot_user=bot_user,
        last_message_at=_utc(2026, 5, 5, 11, 30),
    )
    msg = Message.objects.create(
        conversation=convo, role="user", content="old",
    )
    # Message.created_at is auto_now_add=True; use .update() to override.
    Message.objects.filter(pk=msg.pk).update(
        created_at=_utc(2026, 5, 5, 11, 30),
    )
    blocked, _ = should_skip_due_to_recent_activity(
        bot_user, now=_utc(2026, 5, 5, 12, 0),
    )
    assert blocked is False
