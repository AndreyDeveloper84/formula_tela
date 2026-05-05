"""Phase 3.1 Part 2D.2 T03: nutrition_settings helpers (sync ORM)."""
from __future__ import annotations

import pytest
from model_bakery import baker

from services_app.models import BotUser


pytestmark = pytest.mark.django_db


def test_get_setting_default_when_missing():
    from maxbot.nutrition_settings_helpers import get_setting

    bot_user = baker.make(BotUser, max_user_id=99, nutrition_settings={})
    assert get_setting(bot_user, "daily_report_time", default="21:00") == "21:00"
    assert get_setting(bot_user, "nonexistent_key", default=None) is None


def test_get_setting_returns_existing_value():
    from maxbot.nutrition_settings_helpers import get_setting

    bot_user = baker.make(
        BotUser, max_user_id=99,
        nutrition_settings={"daily_report_time": "18:00"},
    )
    assert get_setting(bot_user, "daily_report_time", default="21:00") == "18:00"


def test_set_setting_persists_to_db():
    from maxbot.nutrition_settings_helpers import set_setting, get_setting

    bot_user = baker.make(BotUser, max_user_id=99, nutrition_settings={})
    set_setting(bot_user, "daily_report_time", "23:00")

    bot_user.refresh_from_db()
    assert bot_user.nutrition_settings["daily_report_time"] == "23:00"
    assert get_setting(bot_user, "daily_report_time", default="21:00") == "23:00"


def test_set_setting_preserves_other_keys():
    from maxbot.nutrition_settings_helpers import set_setting

    bot_user = baker.make(
        BotUser, max_user_id=99,
        nutrition_settings={"food_disclaimer_shown_at": "2026-04-30T12:00:00Z"},
    )
    set_setting(bot_user, "daily_report_time", "18:00")

    bot_user.refresh_from_db()
    assert bot_user.nutrition_settings["daily_report_time"] == "18:00"
    assert bot_user.nutrition_settings["food_disclaimer_shown_at"] == "2026-04-30T12:00:00Z"
