"""maxbot.menu_state — плавающее главное меню (Вариант B)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import sync_to_async
from model_bakery import baker

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


def _fake_sent_message(mid: str = "mid.NEW123"):
    """Mock SendedMessage с body.mid."""
    sent = MagicMock()
    sent.body = MagicMock()
    sent.body.mid = mid
    sent.message = None
    return sent


def _make_bot_with_send(sent_mid: str = "mid.NEW123"):
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=_fake_sent_message(sent_mid))
    bot.edit_message = AsyncMock()
    return bot


# ─── Первая отправка (state пустой) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_first_call_only_sends_no_edit():
    """Если context['last_main_menu_msg_id'] нет — edit_message НЕ вызывается."""
    from maxbot.menu_state import send_with_main_menu, CTX_LAST_MENU_MID

    bot_user = await amake("services_app.BotUser", max_user_id=70001, context={})
    bot = _make_bot_with_send("mid.FIRST")

    await send_with_main_menu(bot=bot, chat_id=100, text="Привет!", bot_user=bot_user)

    bot.edit_message.assert_not_awaited()
    bot.send_message.assert_awaited_once()
    # State обновлён в БД
    await sync_to_async(bot_user.refresh_from_db)()
    assert bot_user.context[CTX_LAST_MENU_MID] == "mid.FIRST"


# ─── Subsequent call (state есть) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_subsequent_call_edits_prev_then_sends():
    """Если context уже содержит prev_id — edit_message убирает меню с него."""
    from maxbot.menu_state import (
        CTX_LAST_MENU_MID, CTX_LAST_MENU_TEXT, send_with_main_menu,
    )

    bot_user = await amake("services_app.BotUser", max_user_id=70002, context={
        CTX_LAST_MENU_MID: "mid.OLD",
        CTX_LAST_MENU_TEXT: "Старый текст",
    })
    bot = _make_bot_with_send("mid.NEW")

    await send_with_main_menu(bot=bot, chat_id=100, text="Новый текст", bot_user=bot_user)

    # edit prev — text сохранён, attachments пусты
    bot.edit_message.assert_awaited_once_with(
        message_id="mid.OLD",
        text="Старый текст",
        attachments=[],
    )
    # send new
    bot.send_message.assert_awaited_once()
    send_kwargs = bot.send_message.await_args.kwargs
    assert send_kwargs["text"] == "Новый текст"
    assert "attachments" in send_kwargs

    # State обновлён на mid.NEW
    await sync_to_async(bot_user.refresh_from_db)()
    assert bot_user.context[CTX_LAST_MENU_MID] == "mid.NEW"
    assert bot_user.context[CTX_LAST_MENU_TEXT] == "Новый текст"


# ─── Edit failure (best-effort) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_failure_does_not_block_send():
    """Если edit_message падает — send всё равно идёт, state обновляется."""
    from maxbot.menu_state import (
        CTX_LAST_MENU_MID, CTX_LAST_MENU_TEXT, send_with_main_menu,
    )

    bot_user = await amake("services_app.BotUser", max_user_id=70003, context={
        CTX_LAST_MENU_MID: "mid.DELETED",
        CTX_LAST_MENU_TEXT: "X",
    })
    bot = _make_bot_with_send("mid.NEW")
    bot.edit_message = AsyncMock(side_effect=RuntimeError("message not found"))

    await send_with_main_menu(bot=bot, chat_id=100, text="Y", bot_user=bot_user)

    bot.send_message.assert_awaited_once()
    await sync_to_async(bot_user.refresh_from_db)()
    assert bot_user.context[CTX_LAST_MENU_MID] == "mid.NEW"


# ─── Send failure (state НЕ обновляется) ──────────────────────────────────


@pytest.mark.asyncio
async def test_send_failure_propagates_state_unchanged():
    from maxbot.menu_state import CTX_LAST_MENU_MID, send_with_main_menu

    bot_user = await amake("services_app.BotUser", max_user_id=70004, context={
        CTX_LAST_MENU_MID: "mid.OLD", "last_main_menu_msg_text": "X",
    })
    bot = MagicMock()
    bot.edit_message = AsyncMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("MAX 503"))

    with pytest.raises(RuntimeError):
        await send_with_main_menu(bot=bot, chat_id=100, text="Y", bot_user=bot_user)

    # State не должен быть обновлён, prev остался mid.OLD
    await sync_to_async(bot_user.refresh_from_db)()
    assert bot_user.context[CTX_LAST_MENU_MID] == "mid.OLD"


# ─── send_message без body.mid (странный SDK ответ) ──────────────────────


@pytest.mark.asyncio
async def test_send_without_mid_skips_state_update():
    """Если SDK не вернул mid — не падаем, просто warning + state не обновляем."""
    from maxbot.menu_state import CTX_LAST_MENU_MID, send_with_main_menu

    bot_user = await amake("services_app.BotUser", max_user_id=70005, context={})
    bot = MagicMock()
    bot.edit_message = AsyncMock()
    sent = MagicMock()
    sent.body = MagicMock()
    sent.body.mid = None
    sent.message = None
    bot.send_message = AsyncMock(return_value=sent)

    await send_with_main_menu(bot=bot, chat_id=100, text="X", bot_user=bot_user)

    await sync_to_async(bot_user.refresh_from_db)()
    assert CTX_LAST_MENU_MID not in bot_user.context


# ─── Empty context (None) graceful ──────────────────────────────────────


@pytest.mark.asyncio
async def test_works_when_context_empty_dict():
    """BotUser.context = {} (default) — не падать, edit не вызывается."""
    from maxbot.menu_state import send_with_main_menu

    bot_user = await amake("services_app.BotUser", max_user_id=70006, context={})
    bot = _make_bot_with_send()

    await send_with_main_menu(bot=bot, chat_id=100, text="X", bot_user=bot_user)
    bot.edit_message.assert_not_awaited()  # nothing to edit
    bot.send_message.assert_awaited_once()
