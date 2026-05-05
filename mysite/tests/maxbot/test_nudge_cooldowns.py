"""Phase 3.2B T04: per-kind cooldown engine."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from model_bakery import baker

from services_app.models import BotUser, NudgeEvent, NudgeMute


pytestmark = pytest.mark.django_db


def _utc(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=ZoneInfo("UTC"))


def test_no_prior_event_not_in_cooldown():
    from maxbot.nudges.cooldowns import is_in_cooldown
    bot_user = baker.make(BotUser, max_user_id=1)
    blocked, _ = is_in_cooldown(
        bot_user, kind="pattern_detected", now=_utc(2026, 5, 5),
    )
    assert blocked is False


def test_recent_event_blocks_pattern_for_21_days():
    """Design §10.5: pattern_detected cooldown=21 days."""
    from maxbot.nudges.cooldowns import is_in_cooldown
    bot_user = baker.make(BotUser, max_user_id=2)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        priority=40, sent_at=_utc(2026, 4, 20),
    )
    # 10 days later → still in cooldown
    blocked, reason = is_in_cooldown(
        bot_user, kind="pattern_detected", now=_utc(2026, 4, 30),
    )
    assert blocked is True
    assert reason == "cooldown_21d"


def test_after_21_days_not_in_cooldown():
    from maxbot.nudges.cooldowns import is_in_cooldown
    bot_user = baker.make(BotUser, max_user_id=3)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        priority=40, sent_at=_utc(2026, 4, 1),
    )
    blocked, _ = is_in_cooldown(
        bot_user, kind="pattern_detected", now=_utc(2026, 4, 25),
    )
    assert blocked is False


def test_less_often_mute_doubles_cooldown():
    """mode=less_often → cooldown × 2."""
    from maxbot.nudges.cooldowns import is_in_cooldown
    bot_user = baker.make(BotUser, max_user_id=4)
    NudgeMute.objects.create(
        bot_user=bot_user, kind="pattern_detected",
        mode="less_often", reason="user_explicit_less",
    )
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        priority=40, sent_at=_utc(2026, 4, 1),
    )
    # 21 days later — normally OK, but mute=less_often doubles to 42
    blocked, _ = is_in_cooldown(
        bot_user, kind="pattern_detected", now=_utc(2026, 4, 25),
    )
    assert blocked is True


def test_zero_cooldown_kinds_never_blocked():
    """booking_continuation cooldown_days=0 — special-case."""
    from maxbot.nudges.cooldowns import is_in_cooldown
    bot_user = baker.make(BotUser, max_user_id=5)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="booking_continuation", nudge_class="service",
        priority=100, sent_at=_utc(2026, 5, 5, 10),
    )
    blocked, _ = is_in_cooldown(
        bot_user, kind="booking_continuation", now=_utc(2026, 5, 5, 11),
    )
    assert blocked is False


def test_unknown_kind_returns_not_blocked():
    """Defensive: kind not in registry → no cooldown enforced."""
    from maxbot.nudges.cooldowns import is_in_cooldown
    bot_user = baker.make(BotUser, max_user_id=6)
    blocked, _ = is_in_cooldown(
        bot_user, kind="nonexistent_kind", now=_utc(2026, 5, 5),
    )
    assert blocked is False
