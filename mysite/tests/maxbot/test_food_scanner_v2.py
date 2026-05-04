"""Phase 3.1 Part 2A T02: NUTRITION_ENABLED gate + FSM-skip в food_scanner."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from maxapi.context.context import MemoryContext


pytestmark = pytest.mark.django_db


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
