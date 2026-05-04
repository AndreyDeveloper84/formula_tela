"""Phase 3.1 Part 2B: water handlers."""
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
async def test_water_menu_shows_today_total_and_amount_keyboard(monkeypatch, settings):
    """[💧 Добавить воду] click → бот показывает 'Сегодня X / Y' + 4 quick-add."""
    from maxbot.handlers.water import on_water_menu
    from maxbot.keyboards import (
        PAYLOAD_WATER_AMOUNT_200, PAYLOAD_WATER_AMOUNT_250,
        PAYLOAD_WATER_AMOUNT_500, PAYLOAD_WATER_AMOUNT_1000,
    )
    from maxbot.services.nutrition_client import WaterTodayResponse

    settings.NUTRITION_ENABLED = True

    today_mock = AsyncMock(return_value=WaterTodayResponse(
        total_ml=1200, norm_ml=2000,
        entries=[],
        raw={},
    ))
    fake_client = MagicMock(get_water_today=today_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:nutrition:water:add")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_menu(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "1.2" in text or "1200" in text
    assert "2.0" in text or "2000" in text

    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert {
        PAYLOAD_WATER_AMOUNT_200, PAYLOAD_WATER_AMOUNT_250,
        PAYLOAD_WATER_AMOUNT_500, PAYLOAD_WATER_AMOUNT_1000,
    } <= payloads


@pytest.mark.asyncio
async def test_water_add_quick_250_calls_ayla_and_shows_undo(monkeypatch, settings):
    """Click [+250 мл] → POST /water/ ml=250, render result + undo button."""
    from maxbot.handlers.water import on_water_add_quick
    from maxbot.keyboards import PAYLOAD_WATER_UNDO_PREFIX
    from maxbot.services.nutrition_client import WaterEntryResponse

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock(return_value=WaterEntryResponse(
        entry_id="W-1", ml=250, water_ml=250, kcal=0,
        milestone_text=None,
        today_total_ml=1450, today_norm_ml=2000,
        alcohol_recovery_hint=False, raw={},
    ))
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:water:add:250")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_add_quick(cb, ctx)

    add_mock.assert_awaited_once()
    kwargs = add_mock.await_args.kwargs
    assert kwargs["ml"] == 250

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "250" in text or "+250" in text
    assert "1.4" in text or "1450" in text

    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert any(p.startswith(PAYLOAD_WATER_UNDO_PREFIX) for p in payloads)
    assert any("W-1" in p for p in payloads)


@pytest.mark.asyncio
async def test_water_add_milestone_text_appears_when_set(monkeypatch, settings):
    """Если Ayla вернула milestone_text — он показывается в render."""
    from maxbot.handlers.water import on_water_add_quick
    from maxbot.services.nutrition_client import WaterEntryResponse

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock(return_value=WaterEntryResponse(
        entry_id="W-2", ml=500, water_ml=500, kcal=0,
        milestone_text="Половина нормы — отлично!",
        today_total_ml=1000, today_norm_ml=2000,
        alcohol_recovery_hint=False, raw={},
    ))
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:water:add:500")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_add_quick(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Половина нормы" in text
