"""Phase 3.1 Part 2A T02: NUTRITION_ENABLED gate + FSM-skip в food_scanner."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from maxapi.context.context import MemoryContext


pytestmark = pytest.mark.django_db


def _flatten_payloads(keyboard) -> set[str]:
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


def _fake_photo_event(chat_id=100, user_id=200, photo_url="https://x.test/p.jpg"):
    """MessageCreated double с одним IMAGE attachment."""
    from maxapi.enums.attachment import AttachmentType

    event = MagicMock()
    event.message = MagicMock()
    event.message.recipient = MagicMock(chat_id=chat_id)
    event.message.sender = MagicMock(user_id=user_id, full_name="Тест")
    payload_obj = MagicMock(url=photo_url)
    att = MagicMock(type=AttachmentType.IMAGE, payload=payload_obj)
    event.message.body = MagicMock(attachments=[att])
    event.bot = MagicMock(send_message=AsyncMock())
    return event


@pytest.mark.asyncio
async def test_photo_blocked_when_nutrition_disabled(monkeypatch, settings):
    """NUTRITION_ENABLED=False → photo НЕ идёт в Ayla, юзер видит COMING_SOON."""
    from maxbot.handlers.food_scanner import on_photo_message

    settings.NUTRITION_ENABLED = False

    scan_mock = AsyncMock()
    fake_client = MagicMock(scan_photo=scan_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )

    monkeypatch.setattr(
        "maxbot.handlers.food_scanner._download_photo",
        AsyncMock(return_value=b"fake"),
    )

    event = _fake_photo_event()
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_photo_message(event, ctx)

    scan_mock.assert_not_awaited()
    event.bot.send_message.assert_awaited_once()
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "Скоро" in text or "разработке" in text.lower()


@pytest.mark.asyncio
async def test_photo_skipped_during_anketa_fsm(monkeypatch, settings):
    """Если state в NutritionAnketaStates.* — photo обработка отменяется,
    юзер видит подсказку «отвечай на вопросы анкеты»."""
    from maxbot.handlers.food_scanner import on_photo_message
    from maxbot.states import NutritionAnketaStates

    settings.NUTRITION_ENABLED = True

    scan_mock = AsyncMock()
    fake_client = MagicMock(scan_photo=scan_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )

    event = _fake_photo_event()
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_photo_message(event, ctx)

    scan_mock.assert_not_awaited()
    event.bot.send_message.assert_awaited_once()
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "анкет" in text.lower() or "вопрос" in text.lower()
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age


@pytest.mark.asyncio
async def test_photo_edit_loading_pattern(monkeypatch, settings):
    """on_photo_message сначала шлёт «👀 Распознаю...», потом edit'ит на
    финальный результат scan'а — не два отдельных сообщения."""
    from maxbot.handlers.food_scanner import on_photo_message
    from maxbot.services.nutrition_client import ScanResponse

    settings.NUTRITION_ENABLED = True

    # send_message returns object with message_id для последующего edit
    sent_msg = MagicMock()
    sent_msg.message_id = "msg-loading-123"
    bot_send_mock = AsyncMock(return_value=sent_msg)
    bot_edit_mock = AsyncMock()

    scan_mock = AsyncMock(return_value=ScanResponse(
        scan_id="s1", dish_name="Паста с курицей", confidence=0.85,
        portion_g=300, nutrition={"calories": 520, "protein_g": 35,
                                  "fat_g": 18, "carbs_g": 55},
        provider="openai", raw={
            "id": "s1", "dish_name": "Паста с курицей", "confidence": 0.85,
            "nutrition": {"calories": 520, "protein_g": 35,
                          "fat_g": 18, "carbs_g": 55},
        },
    ))
    fake_client = MagicMock(scan_photo=scan_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner._download_photo",
        AsyncMock(return_value=b"fake"),
    )
    bot_user = MagicMock(food_scanner_consent_at="2026-01-01", max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    event = _fake_photo_event()
    event.bot.send_message = bot_send_mock
    event.bot.edit_message = bot_edit_mock
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_photo_message(event, ctx)

    # Сначала send_message с loading-text
    bot_send_mock.assert_awaited()
    first_text = bot_send_mock.await_args_list[0].kwargs.get("text", "")
    assert "Распозн" in first_text or "👀" in first_text

    # Потом edit_message с финальным content
    bot_edit_mock.assert_awaited()
    edit_kwargs = bot_edit_mock.await_args.kwargs
    assert edit_kwargs.get("message_id") == "msg-loading-123"
    final_text = edit_kwargs.get("text", "")
    assert "Паста" in final_text


@pytest.mark.asyncio
async def test_on_log_meal_appends_footer_buttons(monkeypatch, settings):
    """После успешного log_meal бот шлёт «✅ Записала ...» + footer
    [💧 Добавить воду][📊 Посмотреть день]."""
    from maxbot.handlers.food_scanner import on_log_meal
    from maxbot.keyboards import (
        PAYLOAD_NUTRITION_ADD_WATER, PAYLOAD_NUTRITION_VIEW_DAY,
    )
    from maxbot.services.nutrition_client import FoodLogResponse

    settings.NUTRITION_ENABLED = True

    log_mock = AsyncMock(return_value=FoodLogResponse(
        log_id="L1", dish_name="Паста",
        meal_type="lunch", calories=520.0, raw={},
    ))
    fake_client = MagicMock(log_meal=log_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = MagicMock()
    cb.callback.payload = "cb:nutrition:log:S1:lunch"
    cb.callback.user = MagicMock(user_id=200, full_name="Тест")
    cb.message.recipient.chat_id = 100
    cb.bot.send_message = AsyncMock()

    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_log_meal(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    kwargs = cb.bot.send_message.await_args.kwargs
    assert "Записала" in kwargs["text"]
    # Footer-keyboard прикреплён
    atts = kwargs.get("attachments") or []
    assert atts, "expected footer-attachment in send_message"
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert PAYLOAD_NUTRITION_ADD_WATER in payloads
    assert PAYLOAD_NUTRITION_VIEW_DAY in payloads
