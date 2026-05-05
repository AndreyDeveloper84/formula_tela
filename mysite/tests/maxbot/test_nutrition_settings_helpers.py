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


def test_is_quiet_hours_at_night_msk():
    """22:00-09:00 МСК → quiet hours."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from maxbot.nutrition_settings_helpers import is_quiet_hours_for_user

    bot_user = baker.make(BotUser, max_user_id=99, timezone="Europe/Moscow")
    night = datetime(2026, 5, 4, 23, 30, tzinfo=ZoneInfo("UTC"))  # 02:30 МСК
    assert is_quiet_hours_for_user(bot_user, now_utc=night) is True

    morning = datetime(2026, 5, 4, 5, 30, tzinfo=ZoneInfo("UTC"))  # 08:30 МСК
    assert is_quiet_hours_for_user(bot_user, now_utc=morning) is True


def test_is_quiet_hours_at_midday_msk():
    """09:00-22:00 МСК → НЕ quiet."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from maxbot.nutrition_settings_helpers import is_quiet_hours_for_user

    bot_user = baker.make(BotUser, max_user_id=99, timezone="Europe/Moscow")
    midday = datetime(2026, 5, 4, 9, 30, tzinfo=ZoneInfo("UTC"))  # 12:30 МСК
    assert is_quiet_hours_for_user(bot_user, now_utc=midday) is False

    evening = datetime(2026, 5, 4, 17, 0, tzinfo=ZoneInfo("UTC"))  # 20:00 МСК
    assert is_quiet_hours_for_user(bot_user, now_utc=evening) is False


def test_calc_proportional_norm_at_wakeup():
    """В 09:00 (wakeup) — elapsed=0 → proportional=0."""
    from maxbot.nutrition_settings_helpers import calc_proportional_norm
    assert calc_proportional_norm(2000, current_local_hour=9) == 0


def test_calc_proportional_norm_at_midday():
    """В 17:00 → elapsed=8 → 8/16 × 2000 = 1000."""
    from maxbot.nutrition_settings_helpers import calc_proportional_norm
    assert calc_proportional_norm(2000, current_local_hour=17) == 1000


def test_calc_proportional_norm_at_evening():
    """В 23:00 → elapsed=14 → 14/16 × 2000 = 1750."""
    from maxbot.nutrition_settings_helpers import calc_proportional_norm
    assert calc_proportional_norm(2000, current_local_hour=23) == 1750


def test_calc_proportional_norm_late_night_capped_at_full():
    """В 01:00 (after midnight) — elapsed≥16 → cap at full norm."""
    from maxbot.nutrition_settings_helpers import calc_proportional_norm
    # 01:00 = wakeup-8 (negative elapsed) → use 0 (Design assumes day stretch
    # 9-1, elapsed=current-wakeup if current>=wakeup, else current+24-wakeup
    # = wraparound). For simplicity treat hours <wakeup as next-day (elapsed=full).
    assert calc_proportional_norm(2000, current_local_hour=1) == 2000


def test_calc_proportional_norm_before_wakeup_clamped_zero():
    """В 08:00 (before wakeup=9) → НЕ wraparound, elapsed=0."""
    from maxbot.nutrition_settings_helpers import calc_proportional_norm
    # ambiguous — Design says day stretches 09-01 (16h). 08:00 = before wakeup,
    # treat as 0 elapsed.
    assert calc_proportional_norm(2000, current_local_hour=8) == 0
