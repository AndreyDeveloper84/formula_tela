"""Phase 3.2B T03: per-class caps engine."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from model_bakery import baker

from services_app.models import BotUser, NudgeEvent


pytestmark = pytest.mark.django_db


def _utc(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=ZoneInfo("UTC"))


def test_care_class_blocks_after_1_per_day():
    from maxbot.nudges.caps import is_capped
    bot_user = baker.make(BotUser, max_user_id=1)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        priority=40, sent_at=_utc(2026, 5, 5, 10),
    )
    blocked, reason = is_capped(
        bot_user, nudge_class="care", now=_utc(2026, 5, 5, 18),
    )
    assert blocked is True
    assert reason == "cap_day_care"


def test_care_class_ok_when_yesterday_send():
    from maxbot.nudges.caps import is_capped
    bot_user = baker.make(BotUser, max_user_id=2)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        priority=40, sent_at=_utc(2026, 5, 4, 10),
    )
    blocked, reason = is_capped(
        bot_user, nudge_class="care", now=_utc(2026, 5, 5, 10),
    )
    assert blocked is False


def test_care_class_blocks_after_2_per_week():
    from maxbot.nudges.caps import is_capped
    bot_user = baker.make(BotUser, max_user_id=3)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        priority=40, sent_at=_utc(2026, 5, 1),
    )
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="health_concern_low", nudge_class="care",
        priority=30, sent_at=_utc(2026, 5, 3),
    )
    blocked, reason = is_capped(
        bot_user, nudge_class="care", now=_utc(2026, 5, 6, 10),
    )
    assert blocked is True
    assert reason == "cap_week_care"


def test_marketing_class_blocks_within_60_days():
    from maxbot.nudges.caps import is_capped
    bot_user = baker.make(BotUser, max_user_id=4)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="cross_promo", nudge_class="marketing",
        priority=20, sent_at=_utc(2026, 4, 1),
    )
    # 30 дней спустя → ещё в окне
    blocked, _ = is_capped(
        bot_user, nudge_class="marketing", now=_utc(2026, 5, 1),
    )
    assert blocked is True


def test_marketing_class_ok_after_60_days():
    from maxbot.nudges.caps import is_capped
    bot_user = baker.make(BotUser, max_user_id=5)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="cross_promo", nudge_class="marketing",
        priority=20, sent_at=_utc(2026, 3, 1),
    )
    blocked, _ = is_capped(
        bot_user, nudge_class="marketing", now=_utc(2026, 5, 5),
    )
    assert blocked is False


def test_service_class_no_daily_cap_only_weekly_5():
    """Design §10.3: SERVICE без жёсткого daily cap, weekly 5."""
    from maxbot.nudges.caps import is_capped
    bot_user = baker.make(BotUser, max_user_id=6)
    # 4 sends за день — всё ОК
    for hour in (8, 12, 14, 18):
        NudgeEvent.objects.create(
            bot_user=bot_user, kind="booking_continuation", nudge_class="service",
            priority=100, sent_at=_utc(2026, 5, 5, hour),
        )
    blocked, _ = is_capped(
        bot_user, nudge_class="service", now=_utc(2026, 5, 5, 20),
    )
    assert blocked is False


def test_service_class_blocked_at_5_per_week():
    from maxbot.nudges.caps import is_capped
    bot_user = baker.make(BotUser, max_user_id=7)
    for day in (1, 2, 3, 4, 5):
        NudgeEvent.objects.create(
            bot_user=bot_user, kind="booking_continuation", nudge_class="service",
            priority=100, sent_at=_utc(2026, 5, day, 10),
        )
    blocked, reason = is_capped(
        bot_user, nudge_class="service", now=_utc(2026, 5, 5, 20),
    )
    assert blocked is True
    assert reason == "cap_week_service"


def test_only_sent_events_count_not_blocked_or_pending():
    """Blocked events не должны входить в quota."""
    from maxbot.nudges.caps import is_capped
    bot_user = baker.make(BotUser, max_user_id=8)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        priority=40, blocked_at=_utc(2026, 5, 5, 10),
        blocked_reason="muted_off",  # не sent
    )
    blocked, _ = is_capped(
        bot_user, nudge_class="care", now=_utc(2026, 5, 5, 18),
    )
    assert blocked is False
