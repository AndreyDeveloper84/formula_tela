"""Phase 3.2A T03: render_overrides_applied helper."""
from __future__ import annotations

from unittest.mock import MagicMock


def _profile(*, goal_overridden_by=None, overrides_applied=None):
    p = MagicMock()
    p.goal_overridden_by = goal_overridden_by
    p.raw = {"overrides_applied": overrides_applied} if overrides_applied else {}
    return p


def test_render_returns_none_when_no_overrides():
    from maxbot.health_overrides_render import render_overrides_applied
    profile = _profile(goal_overridden_by=None, overrides_applied=None)
    assert render_overrides_applied(profile) is None


def test_render_uses_overrides_applied_array_if_present():
    """Forward-compat with Ayla DRF backlog: overrides_applied[] из profile.raw."""
    from maxbot.health_overrides_render import render_overrides_applied
    profile = _profile(
        goal_overridden_by="pregnancy",
        overrides_applied=[
            "Беременность → цель «держать», +200 ккал, +25 г белка, +фолиевая",
            "Аллергия на лактозу → исключаю из советов",
        ],
    )
    text = render_overrides_applied(profile)
    assert text is not None
    assert "Учла важное:" in text
    assert "Беременность" in text
    assert "лактозу" in text


def test_render_falls_back_to_goal_overridden_by_only():
    """Старый Ayla deploy: overrides_applied нет, но goal_overridden_by заполнен."""
    from maxbot.health_overrides_render import render_overrides_applied
    profile = _profile(goal_overridden_by="pregnancy", overrides_applied=None)
    text = render_overrides_applied(profile)
    assert text is not None
    assert "Учла важное" in text
    # Mapped slug → human label
    assert "Беремен" in text or "беремен" in text


def test_render_eating_disorder_label():
    from maxbot.health_overrides_render import render_overrides_applied
    profile = _profile(goal_overridden_by="eating_disorder", overrides_applied=None)
    text = render_overrides_applied(profile)
    assert text is not None
    # Тёплая formulation, не «РПП» (medical jargon)
    assert "поддержи" in text.lower() or "забот" in text.lower()


def test_render_unknown_override_falls_back_to_generic():
    from maxbot.health_overrides_render import render_overrides_applied
    profile = _profile(goal_overridden_by="some_new_thing", overrides_applied=None)
    text = render_overrides_applied(profile)
    assert text is not None
    assert "Учла важное" in text
