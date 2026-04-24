"""Handler /start — главное меню (BotStarted, /start command, кнопка Назад).

Все три entry-point'а ведут в одну функцию `_send_greeting`:
- `bot_started` — первый контакт
- `/start` text command — повторный
- callback `cb:back` — возврат из любого подменю

При каждом из них FSM state сбрасывается → пользователь не остаётся «застрявшим»
в booking-диалоге если решил вернуться в меню.
"""
from __future__ import annotations

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import (
    BotStarted,
    CommandStart,
    MessageCallback,
    MessageCreated,
)

from maxbot import keyboards
from maxbot.personalization import get_or_create_bot_user, greet_text


router = Router()


@router.bot_started()
async def on_bot_started(event: BotStarted, context: MemoryContext) -> None:
    """Первый контакт пользователя с ботом."""
    await _send_greeting(
        bot=event.bot,
        chat_id=event.chat_id,
        user_id=event.user.user_id,
        full_name=event.user.full_name,
        context=context,
    )


@router.message_created(CommandStart())
async def on_start_command(event: MessageCreated, context: MemoryContext) -> None:
    """Текстовая команда /start (повторный или первый)."""
    sender = event.message.sender
    if sender is None:
        # Системные/служебные сообщения без sender — игнорируем
        return
    await _send_greeting(
        bot=event.bot,
        chat_id=event.message.recipient.chat_id,
        user_id=sender.user_id,
        full_name=sender.full_name,
        context=context,
    )


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_BACK)
async def on_back_to_menu(callback: MessageCallback, context: MemoryContext) -> None:
    """Кнопка «← Назад в меню» из любого сценария."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        # Исходное сообщение удалено — некуда отправлять
        return
    await _send_greeting(
        bot=callback.bot,
        chat_id=chat_id,
        user_id=callback.callback.user.user_id,
        full_name=callback.callback.user.full_name,
        context=context,
    )


async def _send_greeting(
    *,
    bot,
    chat_id: int,
    user_id: int,
    full_name: str,
    context: MemoryContext,
) -> None:
    """Общий код: get_or_create + clear FSM + send приветствие с главным меню."""
    bot_user, created = await get_or_create_bot_user(user_id, full_name)
    await context.clear()
    text = greet_text(bot_user, is_new=created)
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.main_menu_keyboard()],
    )
