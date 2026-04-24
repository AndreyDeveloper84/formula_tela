"""Fallback handler — любой текст БЕЗ активного FSM-state ведёт в главное меню.

Регистрируется ПОСЛЕДНИМ в get_routers() — все более специфичные handler'ы
(BookingStates.awaiting_*, /start, callback'и) уже отработали к этому моменту.
"""
from __future__ import annotations

import logging

from maxapi import Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCreated

from maxbot import keyboards, texts


logger = logging.getLogger("maxbot.fallback")
router = Router()


@router.message_created()
async def on_fallback(event: MessageCreated, context: MemoryContext) -> None:
    """Безусловный fallback — все text-message без других matching handler'ов."""
    if event.message.sender is None:
        return  # системные сообщения

    chat_id = event.message.recipient.chat_id
    await event.bot.send_message(
        chat_id=chat_id,
        text=texts.FALLBACK_UNKNOWN_INPUT,
        attachments=[keyboards.main_menu_keyboard()],
    )
