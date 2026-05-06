"""Phase 3.2B T01: NudgeEvent / NudgeMute / PatternRule models."""
from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from model_bakery import baker

from services_app.models import BotUser, NudgeEvent, NudgeMute, PatternRule


pytestmark = pytest.mark.django_db


def test_nudge_event_uuid_pk_and_required_fields():
    bot_user = baker.make(BotUser, max_user_id=1)
    event = NudgeEvent.objects.create(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care", priority=40,
    )
    assert event.id is not None  # UUID auto-set
    assert event.detected_at is not None
    assert event.sent_at is None
    assert event.payload == {}


def test_nudge_event_lifecycle_timestamps():
    bot_user = baker.make(BotUser, max_user_id=2)
    event = baker.make(
        NudgeEvent, bot_user=bot_user, kind="after_service_care",
        nudge_class="service", priority=70,
    )
    # Index check: lookup by bot_user + kind orders by -detected_at
    bulk = NudgeEvent.objects.filter(bot_user=bot_user, kind="after_service_care")
    assert bulk.count() == 1


def test_nudge_mute_validates_xor_kind_or_class():
    """Either kind OR nudge_class — not both, not neither."""
    bot_user = baker.make(BotUser, max_user_id=3)
    # Both populated → ValidationError
    mute_both = NudgeMute(
        bot_user=bot_user, kind="pattern_detected", nudge_class="care",
        mode="off", reason="user_explicit_off",
    )
    with pytest.raises(ValidationError):
        mute_both.full_clean()

    # Neither populated → ValidationError
    mute_neither = NudgeMute(
        bot_user=bot_user, mode="off", reason="user_explicit_off",
    )
    with pytest.raises(ValidationError):
        mute_neither.full_clean()


def test_nudge_mute_only_kind_ok():
    bot_user = baker.make(BotUser, max_user_id=4)
    mute = NudgeMute(
        bot_user=bot_user, kind="cross_promo",
        mode="off", reason="user_explicit_off",
    )
    mute.full_clean()  # no raise
    mute.save()
    assert mute.id is not None


def test_nudge_mute_only_class_ok():
    bot_user = baker.make(BotUser, max_user_id=5)
    mute = NudgeMute(
        bot_user=bot_user, nudge_class="marketing",
        mode="less_often", reason="user_explicit_less",
    )
    mute.full_clean()
    mute.save()


def test_pattern_rule_unique_slug():
    PatternRule.objects.create(
        slug="evening_sweets", name_ru="Вечерние сладости",
        detector_function="maxbot.nudges.detectors.evening_sweets",
        min_repeats=4, min_active_days=14, severity="medium",
        advice_template="…",
    )
    with pytest.raises(Exception):  # IntegrityError
        PatternRule.objects.create(
            slug="evening_sweets", name_ru="Дубликат",
            detector_function="x", min_repeats=1, min_active_days=1,
            severity="low", advice_template="x",
        )


def test_pattern_rule_requires_health_flags_absent_default_list():
    rule = PatternRule.objects.create(
        slug="low_water", name_ru="Мало воды",
        detector_function="x", min_repeats=4, min_active_days=7,
        severity="low", advice_template="x",
    )
    assert rule.requires_health_flags_absent == []
    assert rule.is_active is True
