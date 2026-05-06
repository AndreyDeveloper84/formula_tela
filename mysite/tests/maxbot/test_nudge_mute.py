"""Phase 3.2B T05: mute engine."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from model_bakery import baker

from services_app.models import BotUser, NudgeEvent, NudgeMute


pytestmark = pytest.mark.django_db


def _utc(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=ZoneInfo("UTC"))


def test_no_mute_returns_false():
    from maxbot.nudges.mute import is_muted
    bot_user = baker.make(BotUser, max_user_id=1)
    blocked, _ = is_muted(
        bot_user, kind="pattern_detected", nudge_class="care",
        now=_utc(2026, 5, 5),
    )
    assert blocked is False


def test_kind_off_mute_blocks():
    from maxbot.nudges.mute import is_muted
    bot_user = baker.make(BotUser, max_user_id=2)
    NudgeMute.objects.create(
        bot_user=bot_user, kind="pattern_detected",
        mode="off", reason="user_explicit_off",
    )
    blocked, reason = is_muted(
        bot_user, kind="pattern_detected", nudge_class="care",
        now=_utc(2026, 5, 5),
    )
    assert blocked is True
    assert reason == "muted_kind_off"


def test_class_off_mute_blocks_all_kinds_in_class():
    from maxbot.nudges.mute import is_muted
    bot_user = baker.make(BotUser, max_user_id=3)
    NudgeMute.objects.create(
        bot_user=bot_user, nudge_class="marketing",
        mode="off", reason="user_settings",
    )
    blocked, reason = is_muted(
        bot_user, kind="cross_promo", nudge_class="marketing",
        now=_utc(2026, 5, 5),
    )
    assert blocked is True
    assert reason == "muted_class_off"


def test_less_often_does_not_block_only_doubles():
    """mode=less_often → не блокирует немедленно (handled by cooldown engine)."""
    from maxbot.nudges.mute import is_muted
    bot_user = baker.make(BotUser, max_user_id=4)
    NudgeMute.objects.create(
        bot_user=bot_user, kind="pattern_detected",
        mode="less_often", reason="user_explicit_less",
    )
    blocked, _ = is_muted(
        bot_user, kind="pattern_detected", nudge_class="care",
        now=_utc(2026, 5, 5),
    )
    assert blocked is False


def test_expired_mute_does_not_block():
    from maxbot.nudges.mute import is_muted
    bot_user = baker.make(BotUser, max_user_id=5)
    NudgeMute.objects.create(
        bot_user=bot_user, kind="cross_promo",
        mode="off", reason="user_explicit_off",
        expires_at=_utc(2026, 4, 1),
    )
    blocked, _ = is_muted(
        bot_user, kind="cross_promo", nudge_class="marketing",
        now=_utc(2026, 5, 5),
    )
    assert blocked is False


def test_apply_mute_creates_record():
    from maxbot.nudges.mute import apply_mute
    bot_user = baker.make(BotUser, max_user_id=6)
    apply_mute(
        bot_user, kind="cross_promo", mode="off",
        reason="user_explicit_off",
    )
    assert NudgeMute.objects.filter(
        bot_user=bot_user, kind="cross_promo", mode="off",
    ).count() == 1


def test_maybe_auto_mute_creates_when_two_ignored_in_30d():
    """≥2 ignored same kind in last 30d → auto-mute."""
    from maxbot.nudges.mute import maybe_auto_mute_after_ignore
    bot_user = baker.make(BotUser, max_user_id=7)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="cross_promo", nudge_class="marketing",
        priority=20, ignored_at=_utc(2026, 4, 25),
    )
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="cross_promo", nudge_class="marketing",
        priority=20, ignored_at=_utc(2026, 5, 1),
    )
    created = maybe_auto_mute_after_ignore(
        bot_user, kind="cross_promo", now=_utc(2026, 5, 5),
    )
    assert created is True
    assert NudgeMute.objects.filter(
        bot_user=bot_user, kind="cross_promo",
        reason="auto_ignored_twice",
    ).exists()


def test_maybe_auto_mute_skips_when_only_one_ignored():
    from maxbot.nudges.mute import maybe_auto_mute_after_ignore
    bot_user = baker.make(BotUser, max_user_id=8)
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        priority=40, ignored_at=_utc(2026, 5, 1),
    )
    created = maybe_auto_mute_after_ignore(
        bot_user, kind="pattern_detected", now=_utc(2026, 5, 5),
    )
    assert created is False
    assert not NudgeMute.objects.filter(
        bot_user=bot_user, kind="pattern_detected",
    ).exists()


def test_maybe_auto_mute_idempotent_no_duplicate():
    """If auto-mute already exists, don't create another."""
    from maxbot.nudges.mute import maybe_auto_mute_after_ignore
    bot_user = baker.make(BotUser, max_user_id=9)
    NudgeMute.objects.create(
        bot_user=bot_user, kind="cross_promo",
        mode="off", reason="auto_ignored_twice",
    )
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="cross_promo", nudge_class="marketing",
        priority=20, ignored_at=_utc(2026, 4, 25),
    )
    NudgeEvent.objects.create(
        bot_user=bot_user, kind="cross_promo", nudge_class="marketing",
        priority=20, ignored_at=_utc(2026, 5, 1),
    )
    created = maybe_auto_mute_after_ignore(
        bot_user, kind="cross_promo", now=_utc(2026, 5, 5),
    )
    assert created is False
    assert NudgeMute.objects.filter(
        bot_user=bot_user, kind="cross_promo",
    ).count() == 1  # not duplicated
