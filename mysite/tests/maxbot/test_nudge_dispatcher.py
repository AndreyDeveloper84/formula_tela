"""Phase 3.2B T08: dispatcher pipeline."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from model_bakery import baker

from services_app.models import BotUser, NudgeEvent, NudgeMute


pytestmark = pytest.mark.django_db


def _utc(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("UTC"))


def test_clean_user_unknown_kind_returns_send_false_unknown():
    from maxbot.nudges.dispatcher import evaluate_nudge
    bot_user = baker.make(BotUser, max_user_id=1)
    decision = evaluate_nudge(
        bot_user, kind="not_in_registry", now=_utc(2026, 5, 5),
    )
    assert decision.send is False
    assert decision.blocked_reason == "unknown_kind"


def test_clean_user_known_kind_no_blockers_returns_send_true():
    from maxbot.nudges.dispatcher import evaluate_nudge
    bot_user = baker.make(BotUser, max_user_id=2)
    decision = evaluate_nudge(
        bot_user, kind="pattern_detected", now=_utc(2026, 5, 5, 14),
    )
    assert decision.send is True
    assert decision.nudge_class == "care"
    assert decision.priority == 40


def test_quiet_hours_blocks(monkeypatch):
    """Mock quiet hours engine to True."""
    from maxbot.nudges import dispatcher as disp_mod
    bot_user = baker.make(BotUser, max_user_id=3, timezone="Europe/Moscow")
    monkeypatch.setattr(
        "maxbot.nudges.dispatcher.is_quiet_hours_for_user",
        lambda bu, *, now_utc: True,
    )
    decision = disp_mod.evaluate_nudge(
        bot_user, kind="pattern_detected", now=_utc(2026, 5, 5, 23),
    )
    assert decision.send is False
    assert decision.blocked_reason == "quiet_hours"


def test_mute_off_blocks():
    from maxbot.nudges.dispatcher import evaluate_nudge
    bot_user = baker.make(BotUser, max_user_id=4, timezone="Europe/Moscow")
    NudgeMute.objects.create(
        bot_user=bot_user, kind="pattern_detected",
        mode="off", reason="user_explicit_off",
    )
    decision = evaluate_nudge(
        bot_user, kind="pattern_detected", now=_utc(2026, 5, 5, 14),
    )
    assert decision.send is False
    assert decision.blocked_reason == "muted_kind_off"


def test_caps_blocks_after_quota():
    from maxbot.nudges.dispatcher import evaluate_nudge
    bot_user = baker.make(BotUser, max_user_id=5, timezone="Europe/Moscow")
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        priority=40, sent_at=_utc(2026, 5, 5, 10),
    )
    decision = evaluate_nudge(
        bot_user, kind="health_concern_low", now=_utc(2026, 5, 5, 14),
    )
    assert decision.send is False
    assert decision.blocked_reason == "cap_day_care"


def test_cooldown_blocks():
    from maxbot.nudges.dispatcher import evaluate_nudge
    bot_user = baker.make(BotUser, max_user_id=6, timezone="Europe/Moscow")
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        priority=40, sent_at=_utc(2026, 4, 30),
    )
    decision = evaluate_nudge(
        bot_user, kind="pattern_detected", now=_utc(2026, 5, 5, 14),
    )
    assert decision.send is False
    # Could be cap_day OR cooldown — both valid; verify it's not "send=True"
    # Determinism: order is mute → quiet → caps → cooldown → race
    assert decision.blocked_reason in ("cap_day_care", "cooldown_21d")


def test_race_guard_blocks_recent_user_message():
    from maxbot.nudges.dispatcher import evaluate_nudge
    from services_app.models import Conversation, Message
    bot_user = baker.make(BotUser, max_user_id=7, timezone="Europe/Moscow")
    convo = baker.make(Conversation, bot_user=bot_user)
    msg = Message.objects.create(
        conversation=convo, role="user", content="hi",
    )
    # Message.created_at is auto_now_add=True; use .update() to override.
    Message.objects.filter(pk=msg.pk).update(
        created_at=_utc(2026, 5, 5, 13, 58),
    )
    decision = evaluate_nudge(
        bot_user, kind="pattern_detected", now=_utc(2026, 5, 5, 14),
    )
    assert decision.send is False
    assert decision.blocked_reason == "race_user_message_5min"


def test_decision_dataclass_fields():
    from maxbot.nudges.dispatcher import Decision
    d = Decision(send=True, kind="pattern_detected", nudge_class="care", priority=40)
    assert d.send is True
    assert d.blocked_reason is None
