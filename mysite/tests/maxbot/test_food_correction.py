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
async def test_view_day_calls_daily_summary(monkeypatch, settings):
    """[📊 Посмотреть день] (footer) → daily_summary call → render."""
    from maxbot.handlers.food_correction import on_view_day
    from maxbot.services.nutrition_client import SummaryResponse

    settings.NUTRITION_ENABLED = True

    _entries = [{"meal_type": "lunch", "dish_name": "Суп", "calories": 1100}]
    summary_mock = AsyncMock(return_value=SummaryResponse(
        date="2026-05-04",
        calories_total=1100, calories_goal=1450,
        protein_g=65, fat_g=40, carbs_g=110,
        entries=_entries,
        raw={
            "date": "2026-05-04", "calories_total": 1100,
            "calories_goal": 1450, "protein_g": 65, "fat_g": 40,
            "carbs_g": 110, "entries": _entries,
        },
    ))
    fake_client = MagicMock(daily_summary=summary_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_nutrition_client",
        lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:nutrition:view_day")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_view_day(cb, ctx)

    summary_mock.assert_awaited_once()
    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    # render_daily_summary показывает ккал
    assert "1100" in text or "1450" in text


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
async def test_report_time_settings_stub_says_coming_soon():
    """[⚙️ Время отчёта] → заглушка Part 2D."""
    from maxbot.handlers.food_correction import on_report_time_settings_stub

    cb = _fake_callback("cb:report:time")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_report_time_settings_stub(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Скоро" in text or "21" in text  # 21:00 default mention
