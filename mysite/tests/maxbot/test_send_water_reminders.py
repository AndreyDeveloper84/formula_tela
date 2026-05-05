"""Phase 3.1 Part 2D.2 T08: send_water_reminders Celery task."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from model_bakery import baker

from services_app.models import BotUser


pytestmark = pytest.mark.django_db


def test_send_water_reminders_skipped_when_nutrition_disabled(settings):
    from maxbot.tasks import send_water_reminders

    settings.NUTRITION_ENABLED = False

    baker.make(
        BotUser, max_user_id=99, chat_id=100,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        nutrition_settings={"water_reminders_enabled": True},
    )

    with patch("notifications.max_bot.send_max_message") as send_mock:
        send_water_reminders()
        send_mock.assert_not_called()


def test_send_water_reminders_skips_users_without_opt_in(settings):
    from maxbot.tasks import send_water_reminders

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=100,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        nutrition_settings={"water_reminders_enabled": False},
    )

    with patch("notifications.max_bot.send_max_message") as send_mock, \
         patch("maxbot.services.nutrition_client.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            get_water_today=AsyncMock(),
        )
        send_water_reminders()
        send_mock.assert_not_called()


def test_send_water_reminders_skips_users_in_quiet_hours(settings, monkeypatch):
    """User в quiet hours (22-09 МСК) → пропускается даже если opt-in ON."""
    from maxbot.tasks import send_water_reminders

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=100,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        nutrition_settings={"water_reminders_enabled": True},
        timezone="Europe/Moscow",
    )

    # Mock now=23:00 МСК (in quiet hours)
    fake_now_msk = datetime(2026, 5, 4, 23, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(
        "maxbot.tasks._task_now_msk", lambda: fake_now_msk,
    )

    with patch("notifications.max_bot.send_max_message") as send_mock, \
         patch("maxbot.services.nutrition_client.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            get_water_today=AsyncMock(),
        )
        send_water_reminders()
        send_mock.assert_not_called()


def test_send_water_reminders_skips_users_above_proportional_threshold(
    settings, monkeypatch,
):
    """User уже выпил ≥50% от proportional → пропускается."""
    from maxbot.tasks import send_water_reminders
    from maxbot.services.nutrition_client import WaterTodayResponse

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=100,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        nutrition_settings={"water_reminders_enabled": True},
        timezone="Europe/Moscow",
    )

    # Mock now=15:00 МСК — elapsed=6h, proportional = 6/16 × 2000 = 750
    fake_now_msk = datetime(2026, 5, 4, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(
        "maxbot.tasks._task_now_msk", lambda: fake_now_msk,
    )

    with patch("notifications.max_bot.send_max_message") as send_mock, \
         patch("maxbot.services.nutrition_client.get_nutrition_client") as client_factory:
        # User выпил 500 — выше 50% от 750 (375) → не reminder
        client_factory.return_value = MagicMock(
            get_water_today=AsyncMock(return_value=WaterTodayResponse(
                total_ml=500, norm_ml=2000, entries=[], raw={},
            )),
        )
        send_water_reminders()
        send_mock.assert_not_called()


def test_send_water_reminders_sends_reminder_when_below_threshold(
    settings, monkeypatch,
):
    """User отстаёт <50% от proportional → reminder отправлен."""
    from maxbot.tasks import send_water_reminders
    from maxbot.services.nutrition_client import WaterTodayResponse

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=100,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        nutrition_settings={"water_reminders_enabled": True},
        timezone="Europe/Moscow",
    )

    # 15:00 МСК — proportional = 750, threshold 50% = 375. User=200 → reminder
    fake_now_msk = datetime(2026, 5, 4, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(
        "maxbot.tasks._task_now_msk", lambda: fake_now_msk,
    )

    with patch("notifications.max_bot.send_max_message") as send_mock, \
         patch("maxbot.services.nutrition_client.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            get_water_today=AsyncMock(return_value=WaterTodayResponse(
                total_ml=200, norm_ml=2000, entries=[], raw={},
            )),
        )
        send_water_reminders()
        send_mock.assert_called_once()
        args = send_mock.call_args.args
        assert args[0] == 100  # chat_id


def test_send_water_reminders_skips_users_with_same_day_dismiss(
    settings, monkeypatch,
):
    """User тапнул [Уже пью] сегодня → reminder skipped до завтра."""
    from maxbot.tasks import send_water_reminders
    from maxbot.services.nutrition_client import WaterTodayResponse

    settings.NUTRITION_ENABLED = True

    # Same-day dismiss timestamp (МСК today 10:00)
    today_dismiss = datetime(2026, 5, 4, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    baker.make(
        BotUser, max_user_id=99, chat_id=100,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        nutrition_settings={
            "water_reminders_enabled": True,
            "last_water_dismissed_at": today_dismiss.astimezone(
                ZoneInfo("UTC"),
            ).isoformat(),
        },
        timezone="Europe/Moscow",
    )

    fake_now_msk = datetime(2026, 5, 4, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(
        "maxbot.tasks._task_now_msk", lambda: fake_now_msk,
    )

    with patch("notifications.max_bot.send_max_message") as send_mock, \
         patch("maxbot.services.nutrition_client.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            get_water_today=AsyncMock(return_value=WaterTodayResponse(
                total_ml=200, norm_ml=2000, entries=[], raw={},
            )),
        )
        send_water_reminders()
        send_mock.assert_not_called()
