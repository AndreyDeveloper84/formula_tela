# mysite/tests/maxbot/test_evening_inline.py
"""Part 2D.3 T04: should_trigger_evening_inline pure logic."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest


def _make_bot_user(*, daily_report_time="21:00", evening_inline_shown_at=None):
    bot_user = MagicMock()
    bot_user.timezone = "Europe/Moscow"
    settings = {"daily_report_time": daily_report_time}
    if evening_inline_shown_at is not None:
        settings["evening_inline_shown_at"] = evening_inline_shown_at
    bot_user.nutrition_settings = settings
    return bot_user


def _make_summary(*, entries_count: int):
    summary = MagicMock()
    summary.entries = [
        {"meal_type": "breakfast", "dish_name": "x", "calories": 100}
    ] * entries_count
    return summary


def _msk(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, 5, hour, minute, tzinfo=ZoneInfo("Europe/Moscow"))


def test_trigger_when_all_conditions_met():
    from maxbot.evening_inline import should_trigger_evening_inline
    bot_user = _make_bot_user()
    summary = _make_summary(entries_count=3)
    assert should_trigger_evening_inline(
        bot_user, summary=summary,
        now_local=_msk(19), today_local_date="2026-05-05",
    ) is True


def test_skip_when_hour_below_18():
    from maxbot.evening_inline import should_trigger_evening_inline
    bot_user = _make_bot_user()
    summary = _make_summary(entries_count=3)
    assert should_trigger_evening_inline(
        bot_user, summary=summary,
        now_local=_msk(17, 59), today_local_date="2026-05-05",
    ) is False


def test_skip_when_in_quiet_hours_22plus():
    from maxbot.evening_inline import should_trigger_evening_inline
    bot_user = _make_bot_user()
    summary = _make_summary(entries_count=3)
    assert should_trigger_evening_inline(
        bot_user, summary=summary,
        now_local=_msk(22), today_local_date="2026-05-05",
    ) is False


def test_skip_when_fewer_than_3_entries():
    from maxbot.evening_inline import should_trigger_evening_inline
    bot_user = _make_bot_user()
    summary = _make_summary(entries_count=2)
    assert should_trigger_evening_inline(
        bot_user, summary=summary,
        now_local=_msk(19), today_local_date="2026-05-05",
    ) is False


def test_skip_when_daily_report_off():
    from maxbot.evening_inline import should_trigger_evening_inline
    bot_user = _make_bot_user(daily_report_time="off")
    summary = _make_summary(entries_count=3)
    assert should_trigger_evening_inline(
        bot_user, summary=summary,
        now_local=_msk(19), today_local_date="2026-05-05",
    ) is False


def test_skip_when_already_shown_today():
    from maxbot.evening_inline import should_trigger_evening_inline
    bot_user = _make_bot_user(evening_inline_shown_at="2026-05-05")
    summary = _make_summary(entries_count=3)
    assert should_trigger_evening_inline(
        bot_user, summary=summary,
        now_local=_msk(19), today_local_date="2026-05-05",
    ) is False


def test_trigger_when_shown_yesterday():
    """Idempotency скипает только same-day; вчерашнее значение не блокирует."""
    from maxbot.evening_inline import should_trigger_evening_inline
    bot_user = _make_bot_user(evening_inline_shown_at="2026-05-04")
    summary = _make_summary(entries_count=3)
    assert should_trigger_evening_inline(
        bot_user, summary=summary,
        now_local=_msk(19), today_local_date="2026-05-05",
    ) is True


def test_trigger_at_boundary_hour_18():
    from maxbot.evening_inline import should_trigger_evening_inline
    bot_user = _make_bot_user()
    summary = _make_summary(entries_count=3)
    assert should_trigger_evening_inline(
        bot_user, summary=summary,
        now_local=_msk(18), today_local_date="2026-05-05",
    ) is True


def test_trigger_at_boundary_hour_21_59():
    from maxbot.evening_inline import should_trigger_evening_inline
    bot_user = _make_bot_user()
    summary = _make_summary(entries_count=3)
    assert should_trigger_evening_inline(
        bot_user, summary=summary,
        now_local=_msk(21, 59), today_local_date="2026-05-05",
    ) is True
