"""Scan correction handlers (Phase 3.1 Part 2A T07-T11).

Triggers (cb:scan:correct:* и related payloads):
- `cb:scan:correct:menu:{scan_id}` — открыть menu коррекции (T07)
- `cb:scan:correct:portion:menu` — открыть размер-portion submenu (T08)
- `cb:scan:correct:portion:smaller|normal|larger` — пересчитать порцию (T08, MVP-stub)
- `cb:scan:correct:other_dish` / `add_ingredient` / `delete` — заглушки (T09)
- `cb:scan:retake` / `cb:scan:manual` — переснять / ввести вручную (T09)
- `cb:nutrition:water:add` — заглушка до Part 2B (T10)
- `cb:nutrition:view_day` — daily_summary через эту cb (T11)

Отдельный router потому что food_scanner.py уже жирный (capture +
consent + meal-log) — добавлять correction туда увеличило бы файл вдвое.
"""
from __future__ import annotations

import logging

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback

from maxbot import keyboards


logger = logging.getLogger("maxbot.handlers.food_correction")
router = Router()


CORRECT_MENU_TEXT = "🤖 Что не так с распознаванием?"


@router.message_callback(F.callback.payload.startswith("cb:scan:correct:menu"))
async def on_correct_open_menu(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[✏️ Поправить] на scan-карточке → открыть menu.

    Payload format: `cb:scan:correct:menu:{scan_id}`. scan_id пока не
    используется (menu без scan-context), но extract'ится для T08+
    portion-recalc.
    """
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=CORRECT_MENU_TEXT,
        attachments=[keyboards.food_scan_correct_menu_keyboard()],
    )
