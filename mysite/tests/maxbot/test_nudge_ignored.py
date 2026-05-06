"""Phase 3.2B T07: ignored detection per Design §10.11 (adapted to NudgeEvent)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from model_bakery import baker

from services_app.models import BotUser, Conversation, Message, NudgeEvent


pytestmark = pytest.mark.django_db


def _utc(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=ZoneInfo("UTC"))


def _make_user_msg_at(convo, content: str, ts):
    msg = Message.objects.create(
        conversation=convo, role="user", content=content,
    )
    Message.objects.filter(pk=msg.pk).update(created_at=ts)
    return Message.objects.get(pk=msg.pk)


def test_no_seen_at_returns_false():
    from maxbot.nudges.ignored import is_ignored
    bot_user = baker.make(BotUser, max_user_id=1)
    event = baker.make(
        NudgeEvent, bot_user=bot_user, kind="pattern_detected",
        nudge_class="care", priority=40, seen_at=None,
    )
    assert is_ignored(event, now=_utc(2026, 5, 5)) is False


def test_seen_recently_returns_false():
    """≤24h since seen → not yet ignored."""
    from maxbot.nudges.ignored import is_ignored
    bot_user = baker.make(BotUser, max_user_id=2)
    event = baker.make(
        NudgeEvent, bot_user=bot_user, kind="pattern_detected",
        nudge_class="care", priority=40,
        seen_at=_utc(2026, 5, 4, 18),
    )
    assert is_ignored(event, now=_utc(2026, 5, 5, 12)) is False


def test_seen_24h_user_active_after_no_click_returns_true():
    """≥24h after seen + user message after seen + no clicked_at."""
    from maxbot.nudges.ignored import is_ignored
    bot_user = baker.make(BotUser, max_user_id=3)
    convo = baker.make(Conversation, bot_user=bot_user)
    seen_at = _utc(2026, 5, 4, 10)
    event = baker.make(
        NudgeEvent, bot_user=bot_user, kind="pattern_detected",
        nudge_class="care", priority=40,
        seen_at=seen_at, clicked_at=None,
    )
    _make_user_msg_at(convo, "привет", _utc(2026, 5, 4, 14))
    assert is_ignored(event, now=_utc(2026, 5, 5, 12)) is True


def test_clicked_returns_false():
    from maxbot.nudges.ignored import is_ignored
    bot_user = baker.make(BotUser, max_user_id=4)
    convo = baker.make(Conversation, bot_user=bot_user)
    event = baker.make(
        NudgeEvent, bot_user=bot_user, kind="pattern_detected",
        nudge_class="care", priority=40,
        seen_at=_utc(2026, 5, 4, 10),
        clicked_at=_utc(2026, 5, 4, 11),
    )
    _make_user_msg_at(convo, "ok", _utc(2026, 5, 4, 14))
    assert is_ignored(event, now=_utc(2026, 5, 5, 12)) is False


def test_no_user_activity_after_seen_returns_false():
    """User не активен после seen → не «ignored», просто отсутствует."""
    from maxbot.nudges.ignored import is_ignored
    bot_user = baker.make(BotUser, max_user_id=5)
    event = baker.make(
        NudgeEvent, bot_user=bot_user, kind="pattern_detected",
        nudge_class="care", priority=40,
        seen_at=_utc(2026, 5, 4, 10), clicked_at=None,
    )
    assert is_ignored(event, now=_utc(2026, 5, 5, 12)) is False
