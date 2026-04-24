"""T-12 RED: handler fallback + error middleware."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from maxapi.context.context import MemoryContext

pytestmark = pytest.mark.django_db(transaction=True)


def _make_text_message(*, chat_id=100, user_id=200, text="случайный мусор"):
    sender = MagicMock()
    sender.user_id = user_id
    sender.first_name = "Иван"
    sender.full_name = "Иван"
    body = MagicMock()
    body.text = text
    event = MagicMock()
    event.message = MagicMock()
    event.message.sender = sender
    event.message.recipient = MagicMock()
    event.message.recipient.chat_id = chat_id
    event.message.body = body
    event.bot = MagicMock()
    event.bot.send_message = AsyncMock()
    event.update_type = "message_created"
    return event


# ─── on_fallback ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_sends_main_menu_when_no_state():
    from maxbot.handlers.fallback import on_fallback
    from maxbot.keyboards import PAYLOAD_MENU_BOOK
    event = _make_text_message(user_id=10001, text="что-то непонятное")
    ctx = MemoryContext(chat_id=100, user_id=10001)
    await on_fallback(event, ctx)
    event.bot.send_message.assert_awaited_once()
    payloads = [
        b.payload
        for row in event.bot.send_message.await_args.kwargs["attachments"][0].payload.buttons
        for b in row
    ]
    assert PAYLOAD_MENU_BOOK in payloads


@pytest.mark.asyncio
async def test_fallback_skips_when_message_has_no_sender():
    """Системные сообщения без sender — handler не падает и не шлёт."""
    from maxbot.handlers.fallback import on_fallback
    event = _make_text_message(user_id=10002)
    event.message.sender = None
    ctx = MemoryContext(chat_id=100, user_id=10002)
    await on_fallback(event, ctx)
    event.bot.send_message.assert_not_awaited()


# ─── ErrorAlertMiddleware ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_middleware_alerts_on_handler_exception():
    """Middleware ловит exception от handler'а → шлёт алерт через Telegram."""
    from maxbot.middleware import ErrorAlertMiddleware

    async def handler_that_raises(event_object, data):
        raise RuntimeError("boom!")

    mw = ErrorAlertMiddleware()
    event_object = MagicMock()
    event_object.update_type = "message_created"

    with patch("maxbot.middleware.send_notification_telegram") as mock_alert:
        # Middleware re-raise после алерта
        with pytest.raises(RuntimeError, match="boom"):
            await mw(handler_that_raises, event_object, {})
        mock_alert.assert_called_once()
        text = mock_alert.call_args.args[0]
        assert "RuntimeError" in text or "boom" in text


@pytest.mark.asyncio
async def test_error_middleware_passes_through_when_no_exception():
    from maxbot.middleware import ErrorAlertMiddleware

    async def handler_ok(event_object, data):
        return "ok"

    mw = ErrorAlertMiddleware()
    event_object = MagicMock()
    event_object.update_type = "message_created"
    with patch("maxbot.middleware.send_notification_telegram") as mock_alert:
        result = await mw(handler_ok, event_object, {})
        assert result == "ok"
        mock_alert.assert_not_called()
