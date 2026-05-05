"""Phase 3.1 Part 2C T07: Celery beat task для дневного отчёта в 21:00."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from model_bakery import baker

from services_app.models import BotUser


pytestmark = pytest.mark.django_db


def _mock_msk_hour_21(monkeypatch):
    """Helper: monkeypatch _task_now_msk to return 2026-05-04 21:00 МСК.

    Used so default-time (21:00) hour-filter passes в существующих тестах.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    fake_now = datetime(2026, 5, 4, 21, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr("maxbot.tasks._task_now_msk", lambda: fake_now)


def test_send_daily_reports_skipped_when_nutrition_disabled(settings):
    """NUTRITION_ENABLED=False → task return early, no users iterated."""
    from maxbot.tasks import send_daily_reports

    settings.NUTRITION_ENABLED = False

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        baker.make(
            BotUser, max_user_id=99,
            chat_id=100, nutrition_onboarded_at="2026-04-30T12:00:00Z",
        )

        send_daily_reports()

        send_mock.assert_not_called()
        client_factory.assert_not_called()


def test_send_daily_reports_skips_users_without_chat_id(settings):
    """User без chat_id → пропускается (некуда слать)."""
    from maxbot.tasks import send_daily_reports

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99,
        chat_id=None,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(),
            get_water_today=AsyncMock(),
        )

        send_daily_reports()

        send_mock.assert_not_called()


def test_send_daily_reports_skips_non_onboarded_users(settings):
    """User без nutrition_onboarded_at → пропускается."""
    from maxbot.tasks import send_daily_reports

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=100,
        nutrition_onboarded_at=None,
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(),
            get_water_today=AsyncMock(),
        )

        send_daily_reports()

        send_mock.assert_not_called()


def test_send_daily_reports_dispatches_to_eligible_user(settings, monkeypatch):
    """User onboarded + chat_id → daily_summary + get_water_today + send_max_message."""
    from maxbot.tasks import send_daily_reports
    from maxbot.services.nutrition_client import (
        SummaryResponse, WaterTodayResponse,
    )

    settings.NUTRITION_ENABLED = True
    _mock_msk_hour_21(monkeypatch)

    baker.make(
        BotUser, max_user_id=99, chat_id=12345,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        health_flags={},
    )

    summary = SummaryResponse(
        date="2026-05-04",
        calories_total=1380, calories_goal=1450,
        protein_g=98, fat_g=52, carbs_g=145,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "борщ", "calories": 520},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 380},
            {"meal_type": "snack", "dish_name": "яблоко", "calories": 160},
        ],
        raw={},
    )
    water_today = WaterTodayResponse(
        total_ml=1800, norm_ml=2000, entries=[], raw={},
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(return_value=summary),
            get_water_today=AsyncMock(return_value=water_today),
        )

        send_daily_reports()

        send_mock.assert_called_once()
        args, kwargs = send_mock.call_args
        # send_max_message(chat_id, text, attachments=[...]) — позиционный chat_id
        assert args[0] == 12345 or kwargs.get("chat_id") == 12345
        text = args[1] if len(args) > 1 else kwargs.get("text", "")
        # Hybrid format — есть kcal + water
        assert "1380" in text or "1450" in text
        assert "1.8" in text or "1800" in text
        # Footer keyboard прикреплён (UX consistency с /день и view_day footer button)
        atts = args[2] if len(args) > 2 else kwargs.get("attachments")
        assert atts, "expected footer keyboard attached в push"


def test_send_daily_reports_eating_disorder_mode_omits_calories(settings, monkeypatch):
    """User с eating_disorder=True → render без чисел калорий."""
    from maxbot.tasks import send_daily_reports
    from maxbot.services.nutrition_client import (
        SummaryResponse, WaterTodayResponse,
    )

    settings.NUTRITION_ENABLED = True
    _mock_msk_hour_21(monkeypatch)

    baker.make(
        BotUser, max_user_id=99, chat_id=12345,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        health_flags={"eating_disorder": True},
    )

    summary = SummaryResponse(
        date="2026-05-04",
        calories_total=1300, calories_goal=1450,
        protein_g=80, fat_g=40, carbs_g=130,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 380},
        ],
        raw={},
    )
    water_today = WaterTodayResponse(
        total_ml=1800, norm_ml=2000, entries=[], raw={},
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(return_value=summary),
            get_water_today=AsyncMock(return_value=water_today),
        )

        send_daily_reports()

        send_mock.assert_called_once()
        args = send_mock.call_args.args
        text = args[1] if len(args) > 1 else send_mock.call_args.kwargs.get("text", "")
        # No calorie numbers
        assert "1300" not in text
        assert "1450" not in text
        # Supportive vibe
        assert "Как ты сегодня" in text or "День получился" in text


def test_send_daily_reports_continues_after_user_failure(settings, monkeypatch):
    """Если Ayla падает на user A — task продолжает с user B."""
    from maxbot.tasks import send_daily_reports
    from maxbot.services.nutrition_client import (
        SummaryResponse, WaterTodayResponse, NutritionUnavailableError,
    )

    settings.NUTRITION_ENABLED = True
    _mock_msk_hour_21(monkeypatch)

    baker.make(
        BotUser, max_user_id=99, chat_id=12345,
        nutrition_onboarded_at="2026-04-30T12:00:00Z", health_flags={},
    )
    baker.make(
        BotUser, max_user_id=100, chat_id=12346,
        nutrition_onboarded_at="2026-04-30T12:00:00Z", health_flags={},
    )

    # User 99 — Ayla падает; user 100 — успех
    async def flaky_summary(*, external_user_id):
        if external_user_id == "bot:99":
            raise NutritionUnavailableError("simulated")
        return SummaryResponse(
            date="2026-05-04", calories_total=1100, calories_goal=1450,
            protein_g=65, fat_g=40, carbs_g=110,
            entries=[
                {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
                {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
                {"meal_type": "dinner", "dish_name": "рыба", "calories": 330},
            ],
            raw={},
        )

    water_today = WaterTodayResponse(
        total_ml=1500, norm_ml=2000, entries=[], raw={},
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=flaky_summary,
            get_water_today=AsyncMock(return_value=water_today),
        )

        result = send_daily_reports()

        # User 99 skipped, user 100 sent
        assert send_mock.call_count == 1
        assert result == {"sent": 1, "skipped": 1}


def test_send_daily_reports_skips_users_with_off_setting(settings):
    """User с daily_report_time='off' → пропускается."""
    from maxbot.tasks import send_daily_reports

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=12345,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        nutrition_settings={"daily_report_time": "off"},
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(),
            get_water_today=AsyncMock(),
        )

        send_daily_reports()

        send_mock.assert_not_called()


def test_send_daily_reports_filters_by_current_local_hour(settings, monkeypatch):
    """User с daily_report_time='18:00' → отправляется только когда current_local_hour == 18."""
    from maxbot.tasks import send_daily_reports
    from maxbot.services.nutrition_client import (
        SummaryResponse, WaterTodayResponse,
    )

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=12345,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        nutrition_settings={"daily_report_time": "18:00"},
        timezone="Europe/Moscow",
    )

    summary = SummaryResponse(
        date="2026-05-04", calories_total=1100, calories_goal=1450,
        protein_g=65, fat_g=40, carbs_g=110,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 330},
        ],
        raw={},
    )

    # Mock current MSK hour to 18
    from datetime import datetime
    from zoneinfo import ZoneInfo
    fake_now = datetime(2026, 5, 4, 18, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(
        "maxbot.tasks._task_now_msk", lambda: fake_now,
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(return_value=summary),
            get_water_today=AsyncMock(return_value=WaterTodayResponse(
                total_ml=0, norm_ml=2000, entries=[], raw={},
            )),
        )

        send_daily_reports()

        send_mock.assert_called_once()


def test_send_daily_reports_skips_user_when_hour_not_match(settings, monkeypatch):
    """User c daily_report_time='21:00', current_hour=18 → пропускается."""
    from maxbot.tasks import send_daily_reports

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=12345,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        nutrition_settings={"daily_report_time": "21:00"},
        timezone="Europe/Moscow",
    )

    from datetime import datetime
    from zoneinfo import ZoneInfo
    fake_now = datetime(2026, 5, 4, 18, 0, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(
        "maxbot.tasks._task_now_msk", lambda: fake_now,
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(),
            get_water_today=AsyncMock(),
        )

        send_daily_reports()

        send_mock.assert_not_called()
