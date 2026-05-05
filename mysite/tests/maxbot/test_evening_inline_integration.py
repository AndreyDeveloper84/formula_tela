"""Part 2D.3 T05: on_log_meal triggers evening inline when conditions met."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest


@pytest.mark.asyncio
async def test_on_log_meal_sends_evening_inline_when_eligible(monkeypatch):
    """После log_meal в 19:00 МСК с 3 entries → второе сообщение с дневным отчётом."""
    from maxbot.handlers.food_scanner import on_log_meal
    from maxbot.services.nutrition_client import (
        FoodLogResponse, SummaryResponse, WaterTodayResponse,
    )

    bot_user = MagicMock(
        max_user_id=42,
        nutrition_settings={"daily_report_time": "21:00"},
        timezone="Europe/Moscow",
        health_flags={},
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.external_user_id_for", lambda bu: "ext-42",
    )

    fake_log = FoodLogResponse(
        log_id="L1", dish_name="каша", meal_type="breakfast",
        calories=320.0, raw={},
    )
    fake_summary = SummaryResponse(
        date="2026-05-05", calories_total=1100, calories_goal=1450,
        protein_g=65, fat_g=40, carbs_g=110,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 330},
        ],
        raw={}, ai_comment="Отличный день!",
    )
    fake_client = MagicMock(
        log_meal=AsyncMock(return_value=fake_log),
        daily_summary=AsyncMock(return_value=fake_summary),
        get_water_today=AsyncMock(return_value=WaterTodayResponse(
            total_ml=500, norm_ml=2000, entries=[], raw={},
        )),
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )

    # Mock «now» to 19:00 МСК
    fake_now = datetime(2026, 5, 5, 19, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner._now_msk", lambda: fake_now,
    )

    set_setting_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.set_setting", set_setting_mock,
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()
    callback = MagicMock()
    callback.callback.payload = "cb:nutrition:log:scan-1:dinner"
    callback.callback.user = MagicMock(user_id=42, full_name="Аня")
    callback.message.recipient.chat_id = 100
    callback.bot = bot

    await on_log_meal(callback, MagicMock())

    # 2 messages sent: log ack + evening inline
    assert bot.send_message.await_count == 2

    # Second message contains daily report text
    second_call = bot.send_message.await_args_list[1]
    text = second_call.kwargs.get("text", "")
    assert "Итоги дня" in text or "🎯" in text

    # evening_inline_shown_at persisted
    set_setting_mock.assert_called_once()
    call_args = set_setting_mock.call_args.args
    assert call_args[1] == "evening_inline_shown_at"
    assert call_args[2] == "2026-05-05"


@pytest.mark.asyncio
async def test_on_log_meal_no_evening_inline_at_morning(monkeypatch):
    """log_meal в 09:00 МСК → только ack, без evening inline."""
    from maxbot.handlers.food_scanner import on_log_meal
    from maxbot.services.nutrition_client import FoodLogResponse, SummaryResponse

    bot_user = MagicMock(
        max_user_id=42,
        nutrition_settings={"daily_report_time": "21:00"},
        timezone="Europe/Moscow",
        health_flags={},
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.external_user_id_for", lambda bu: "ext-42",
    )

    fake_log = FoodLogResponse(
        log_id="L1", dish_name="каша", meal_type="breakfast",
        calories=320.0, raw={},
    )
    fake_client = MagicMock(log_meal=AsyncMock(return_value=fake_log))
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )

    fake_now = datetime(2026, 5, 5, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner._now_msk", lambda: fake_now,
    )

    set_setting_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.set_setting", set_setting_mock,
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()
    callback = MagicMock()
    callback.callback.payload = "cb:nutrition:log:scan-1:breakfast"
    callback.callback.user = MagicMock(user_id=42, full_name="Аня")
    callback.message.recipient.chat_id = 100
    callback.bot = bot

    await on_log_meal(callback, MagicMock())

    # Only the log ack — no second message, no daily_summary fetch
    assert bot.send_message.await_count == 1
    assert not fake_client.daily_summary.called  # never even fetched
    set_setting_mock.assert_not_called()


@pytest.mark.asyncio
async def test_on_log_meal_evening_inline_failure_silent(monkeypatch):
    """daily_summary throws → log_meal flow всё равно success, no crash."""
    from maxbot.handlers.food_scanner import on_log_meal
    from maxbot.services.nutrition_client import (
        FoodLogResponse, NutritionUnavailableError,
    )

    bot_user = MagicMock(
        max_user_id=42,
        nutrition_settings={"daily_report_time": "21:00"},
        timezone="Europe/Moscow",
        health_flags={},
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.external_user_id_for", lambda bu: "ext-42",
    )

    fake_log = FoodLogResponse(
        log_id="L1", dish_name="рыба", meal_type="dinner",
        calories=330.0, raw={},
    )
    fake_client = MagicMock(
        log_meal=AsyncMock(return_value=fake_log),
        daily_summary=AsyncMock(side_effect=NutritionUnavailableError("circuit_open")),
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )

    fake_now = datetime(2026, 5, 5, 19, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner._now_msk", lambda: fake_now,
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()
    callback = MagicMock()
    callback.callback.payload = "cb:nutrition:log:scan-1:dinner"
    callback.callback.user = MagicMock(user_id=42, full_name="Аня")
    callback.message.recipient.chat_id = 100
    callback.bot = bot

    # Must not raise
    await on_log_meal(callback, MagicMock())

    # Only the log ack survives
    assert bot.send_message.await_count == 1
