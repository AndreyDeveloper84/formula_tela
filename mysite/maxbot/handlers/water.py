"""Water flow handlers (Phase 3.1 Part 2B).

Triggers:
- `cb:nutrition:water:add` (PAYLOAD_NUTRITION_ADD_WATER) — open menu (T02)
- `cb:water:add:{ml}` — quick or extended add (T03)
- `cb:water:more` — show extended keyboard (T05)
- `cb:water:undo:{entry_id}` — DELETE undo_water (T04)
- `/вода` text command — alias для open menu (T06)

Server-side details (Ayla, см. ayla-spec §2):
- water_coefficient applied per beverage
- milestone_text generated server-side per-day idempotently
- alcohol_recovery_hint flag (true для wine/beer/spirits)
- 15-minute restore window after soft-delete
"""
from __future__ import annotations

import logging

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback

from maxbot import ai_ui, keyboards
from maxbot.personalization import get_or_create_bot_user
from maxbot.services.ayla_user_proxy import external_user_id_for
from maxbot.services.nutrition_client import (
    NutritionAPIError,
    NutritionUnavailableError,
    get_nutrition_client,
)


logger = logging.getLogger("maxbot.handlers.water")
router = Router()


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_NUTRITION_ADD_WATER,
)
async def on_water_menu(callback: MessageCallback, context: MemoryContext) -> None:
    """[💧 Добавить воду] entry — show today_total + 4 quick-add buttons."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return
    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)

    client = get_nutrition_client()
    try:
        today = await client.get_water_today(
            external_user_id=external_user_id_for(bot_user),
        )
    except NutritionUnavailableError:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Учёт воды временно недоступен. Попробуй через минуту.",
        )
        return
    except NutritionAPIError as exc:
        logger.exception("water.menu.api_error user=%s err=%s",
                         bot_user.max_user_id, exc)
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Не получилось загрузить статус. Попробуй позже.",
        )
        return

    text = ai_ui.render_water_status(today)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.water_amount_keyboard()],
    )
