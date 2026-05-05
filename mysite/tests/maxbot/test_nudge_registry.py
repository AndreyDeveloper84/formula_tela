"""Phase 3.2B T02: nudge registry — kind → class/priority/cooldown."""
from __future__ import annotations

import pytest


def test_nudge_class_enum_three_values():
    from maxbot.nudges.registry import NudgeClass
    assert NudgeClass.SERVICE == "service"
    assert NudgeClass.CARE == "care"
    assert NudgeClass.MARKETING == "marketing"


def test_registry_contains_design_doc_kinds():
    from maxbot.nudges.registry import NUDGE_REGISTRY, NudgeClass
    expected_kinds = {
        "booking_continuation", "health_concern_high", "health_concern_medium",
        "after_service_care", "weekly_unlock", "returning_success",
        "pattern_detected", "pattern_followup", "health_concern_low",
        "cross_promo", "reengagement",
    }
    assert expected_kinds <= set(NUDGE_REGISTRY.keys())


def test_registry_priorities_match_design():
    """Design §10.2 priority table."""
    from maxbot.nudges.registry import NUDGE_REGISTRY
    assert NUDGE_REGISTRY["booking_continuation"]["priority"] == 100
    assert NUDGE_REGISTRY["health_concern_high"]["priority"] == 90
    assert NUDGE_REGISTRY["after_service_care"]["priority"] == 70
    assert NUDGE_REGISTRY["pattern_detected"]["priority"] == 40
    assert NUDGE_REGISTRY["cross_promo"]["priority"] == 20
    assert NUDGE_REGISTRY["reengagement"]["priority"] == 10


def test_registry_classes_match_design():
    from maxbot.nudges.registry import NUDGE_REGISTRY, NudgeClass
    assert NUDGE_REGISTRY["booking_continuation"]["class"] == NudgeClass.SERVICE
    assert NUDGE_REGISTRY["after_service_care"]["class"] == NudgeClass.SERVICE
    assert NUDGE_REGISTRY["health_concern_high"]["class"] == NudgeClass.CARE
    assert NUDGE_REGISTRY["pattern_detected"]["class"] == NudgeClass.CARE
    assert NUDGE_REGISTRY["cross_promo"]["class"] == NudgeClass.MARKETING


def test_registry_cooldowns_match_design():
    """Design §10.5 cooldown table (in days)."""
    from maxbot.nudges.registry import NUDGE_REGISTRY
    assert NUDGE_REGISTRY["reengagement"]["cooldown_days"] == 30
    assert NUDGE_REGISTRY["pattern_detected"]["cooldown_days"] == 21
    assert NUDGE_REGISTRY["health_concern_low"]["cooldown_days"] == 30
    assert NUDGE_REGISTRY["health_concern_medium"]["cooldown_days"] == 14
    assert NUDGE_REGISTRY["health_concern_high"]["cooldown_days"] == 7
    assert NUDGE_REGISTRY["cross_promo"]["cooldown_days"] == 60
    assert NUDGE_REGISTRY["returning_success"]["cooldown_days"] == 30


def test_get_kind_meta_returns_dict_or_none():
    from maxbot.nudges.registry import get_kind_meta, NudgeClass
    meta = get_kind_meta("pattern_detected")
    assert meta is not None
    assert meta["class"] == NudgeClass.CARE
    assert meta["priority"] == 40
    # Unknown kind → None (defensive)
    assert get_kind_meta("does_not_exist") is None
