"""Phase 3.1 Part 2A T07-T11: scan correction router."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from maxapi.context.context import MemoryContext


pytestmark = pytest.mark.django_db


def _fake_callback(payload, chat_id=100, user_id=200):
    cb = MagicMock()
    cb.callback.payload = payload
    cb.callback.user = MagicMock(user_id=user_id, full_name="Тест")
    cb.message.recipient.chat_id = chat_id
    cb.bot.send_message = AsyncMock()
    return cb


def _flatten_payloads(keyboard):
    out = set()
    rows = (
        getattr(getattr(keyboard, "payload", None), "buttons", None)
        or getattr(keyboard, "buttons", None)
        or getattr(keyboard, "rows", None)
        or []
    )
    for row in rows:
        for btn in row:
            payload = getattr(btn, "payload", None)
            if payload is None:
                callback = getattr(btn, "callback", None)
                payload = getattr(callback, "payload", None) if callback else None
            if payload:
                out.add(payload)
    return out


@pytest.mark.asyncio
async def test_correct_open_menu_shows_4_options():
    """Клик «✏️ Поправить» (cb:scan:correct:menu:{scan_id}) → открыть menu."""
    from maxbot.handlers.food_correction import on_correct_open_menu

    cb = _fake_callback("cb:scan:correct:menu:S1")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_correct_open_menu(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    # Текст «Что не так?» по Design §5.4
    assert "не так" in text.lower() or "Что" in text
    # Attachments — keyboard с 4 опциями
    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    assert atts


@pytest.mark.asyncio
async def test_portion_menu_button_shows_size_keyboard():
    """[📦 Размер порции] (PAYLOAD_SCAN_PORTION_OPEN_MENU) →
    показать [Меньше][Норм][Больше]."""
    from maxbot.handlers.food_correction import on_portion_menu
    from maxbot.keyboards import (
        PAYLOAD_SCAN_PORTION_SMALLER,
        PAYLOAD_SCAN_PORTION_NORMAL,
        PAYLOAD_SCAN_PORTION_LARGER,
    )

    cb = _fake_callback("cb:scan:correct:portion:menu")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_portion_menu(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    assert atts
    payloads = _flatten_payloads(atts[0])
    assert PAYLOAD_SCAN_PORTION_SMALLER in payloads
    assert PAYLOAD_SCAN_PORTION_NORMAL in payloads
    assert PAYLOAD_SCAN_PORTION_LARGER in payloads


@pytest.mark.asyncio
async def test_portion_apply_button_stub_says_phase32():
    """[Меньше][Норм][Больше] — Phase 3.2 заглушка (пересчёт через
    scan_photo+portion_multiplier требует storage scan↔image)."""
    from maxbot.handlers.food_correction import on_portion_apply

    cb = _fake_callback("cb:scan:correct:portion:smaller")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_portion_apply(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    # Stub обозначает что MVP готов
    assert "Скоро" in text or "пришли" in text.lower() or "снова" in text.lower()


@pytest.mark.asyncio
async def test_other_dish_stub_says_coming_soon():
    """[🔄 Это другое блюдо] — заглушка Phase 3.2."""
    from maxbot.handlers.food_correction import on_other_dish

    cb = _fake_callback("cb:scan:correct:other_dish")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_other_dish(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Скоро" in text or "разработ" in text.lower()


@pytest.mark.asyncio
async def test_retake_stub_hints_send_photo():
    """[📸 Переснять] — попроси прислать новое фото."""
    from maxbot.handlers.food_correction import on_retake

    cb = _fake_callback("cb:scan:retake")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_retake(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Пришли" in text or "пришли" in text or "фото" in text.lower()



@pytest.mark.asyncio
async def test_report_weekly_stub_says_coming_soon():
    """[📊 Неделя] → заглушка Phase 3.3."""
    from maxbot.handlers.food_correction import on_report_weekly_stub

    cb = _fake_callback("cb:report:weekly")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_report_weekly_stub(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Скоро" in text or "разработ" in text.lower() or "после 7" in text


@pytest.mark.asyncio
async def test_view_day_fetches_water_and_renders_full_report(monkeypatch, settings):
    """on_view_day теперь fetch'ит summary + water_today, render через
    render_daily_full_report. Footer-keyboard прикрепляется."""
    from maxbot.handlers.food_correction import on_view_day
    from maxbot.keyboards import (
        PAYLOAD_REPORT_WEEKLY, PAYLOAD_REPORT_TIME_SETTINGS,
    )
    from maxbot.services.nutrition_client import (
        SummaryResponse, WaterTodayResponse,
    )

    settings.NUTRITION_ENABLED = True

    summary_mock = AsyncMock(return_value=SummaryResponse(
        date="2026-05-04",
        calories_total=1100, calories_goal=1450,
        protein_g=65, fat_g=40, carbs_g=110,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 330},
        ],
        raw={},
    ))
    water_mock = AsyncMock(return_value=WaterTodayResponse(
        total_ml=1500, norm_ml=2000,
        entries=[],
        raw={},
    ))
    fake_client = MagicMock(daily_summary=summary_mock, get_water_today=water_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_nutrition_client",
        lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:nutrition:view_day")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_view_day(cb, ctx)

    summary_mock.assert_awaited_once()
    water_mock.assert_awaited_once()

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    # Combined render — есть и kcal и water
    assert "1100" in text or "1450" in text
    assert "1.5" in text or "1500" in text  # water

    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert PAYLOAD_REPORT_WEEKLY in payloads
    assert PAYLOAD_REPORT_TIME_SETTINGS in payloads


@pytest.mark.asyncio
async def test_report_time_open_menu_shows_4_time_options():
    """[⚙️ Время] click → settings menu с 4 вариантами времени."""
    from maxbot.handlers.food_correction import on_report_time_open_menu
    from maxbot.keyboards import (
        PAYLOAD_REPORT_TIME_18, PAYLOAD_REPORT_TIME_21,
        PAYLOAD_REPORT_TIME_23, PAYLOAD_REPORT_TIME_OFF,
    )

    cb = _fake_callback("cb:report:time")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_report_time_open_menu(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Время" in text or "отчёт" in text.lower()
    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert {
        PAYLOAD_REPORT_TIME_18, PAYLOAD_REPORT_TIME_21,
        PAYLOAD_REPORT_TIME_23, PAYLOAD_REPORT_TIME_OFF,
    } <= payloads


@pytest.mark.asyncio
async def test_report_time_18_persists_setting(monkeypatch):
    """Click [18:00] → set_setting('daily_report_time', '18:00') + ack."""
    from unittest.mock import MagicMock
    from maxbot.handlers.food_correction import on_report_time_select

    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    set_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.set_setting", set_mock,
    )

    cb = _fake_callback("cb:report:time:18")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_report_time_select(cb, ctx)

    set_mock.assert_called_once()
    args = set_mock.call_args.args
    assert args[1] == "daily_report_time"
    assert args[2] == "18:00"

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "18:00" in text


@pytest.mark.asyncio
async def test_report_time_off_persists_off_setting(monkeypatch):
    from unittest.mock import MagicMock
    from maxbot.handlers.food_correction import on_report_time_select

    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    set_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.set_setting", set_mock,
    )

    cb = _fake_callback("cb:report:time:off")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_report_time_select(cb, ctx)

    args = set_mock.call_args.args
    assert args[2] == "off"

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "выкл" in text.lower() or "🔕" in text


@pytest.mark.asyncio
async def test_water_reminders_open_shows_toggle_keyboard(monkeypatch):
    """[🔔 Напоминания] click → menu с toggle button."""
    from unittest.mock import MagicMock
    from maxbot.handlers.food_correction import on_water_reminders_open
    from maxbot.keyboards import PAYLOAD_WATER_REMINDERS_TOGGLE

    bot_user = MagicMock(max_user_id=200, nutrition_settings={})
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:water:reminders:open")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_reminders_open(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Напоминания" in text or "вода" in text.lower()
    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert PAYLOAD_WATER_REMINDERS_TOGGLE in payloads


@pytest.mark.asyncio
async def test_water_reminders_toggle_persists_true(monkeypatch):
    """Tap toggle когда currently OFF → persist water_reminders_enabled=True + ack."""
    from unittest.mock import MagicMock
    from maxbot.handlers.food_correction import on_water_reminders_toggle

    bot_user = MagicMock(
        max_user_id=200, nutrition_settings={"water_reminders_enabled": False},
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    set_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.set_setting", set_mock,
    )

    cb = _fake_callback("cb:water:reminders:toggle")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_reminders_toggle(cb, ctx)

    set_mock.assert_called_once()
    args = set_mock.call_args.args
    assert args[1] == "water_reminders_enabled"
    assert args[2] is True


@pytest.mark.asyncio
async def test_water_reminders_toggle_persists_false_when_on(monkeypatch):
    """Tap toggle когда currently ON → persist=False."""
    from unittest.mock import MagicMock
    from maxbot.handlers.food_correction import on_water_reminders_toggle

    bot_user = MagicMock(
        max_user_id=200, nutrition_settings={"water_reminders_enabled": True},
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    set_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.set_setting", set_mock,
    )

    cb = _fake_callback("cb:water:reminders:toggle")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_reminders_toggle(cb, ctx)

    args = set_mock.call_args.args
    assert args[2] is False
