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
import time
import uuid

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback, MessageCreated

from maxbot import ai_ui, keyboards
from maxbot.personalization import get_or_create_bot_user
from maxbot.services.ayla_user_proxy import external_user_id_for
from maxbot.services.nutrition_client import (
    NutritionAPIError,
    NutritionUnavailableError,
    get_nutrition_client,
)
from django.conf import settings as django_settings
from maxbot.states import NutritionAnketaStates


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

    if not getattr(django_settings, "NUTRITION_ENABLED", False):
        await callback.bot.send_message(
            chat_id=chat_id,
            text=(
                "💧 Учёт воды скоро добавлю — фича в разработке. "
                "Когда подключим — будешь следить за нормой воды и напитков."
            ),
        )
        return

    state = await context.get_state()
    if state is not None and str(state).startswith("NutritionAnketaStates"):
        await callback.bot.send_message(
            chat_id=chat_id,
            text=(
                "Сейчас отвечаю на вопросы анкеты — "
                "пришли число / нажми кнопку, чтобы продолжить."
            ),
        )
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


# Map payload → ml для quick + extended (single source of truth)
_PAYLOAD_TO_ML = {
    keyboards.PAYLOAD_WATER_AMOUNT_200: 200,
    keyboards.PAYLOAD_WATER_AMOUNT_250: 250,
    keyboards.PAYLOAD_WATER_AMOUNT_500: 500,
    keyboards.PAYLOAD_WATER_AMOUNT_1000: 1000,
    keyboards.PAYLOAD_WATER_EXTENDED_150: 150,
    keyboards.PAYLOAD_WATER_EXTENDED_300: 300,
    keyboards.PAYLOAD_WATER_EXTENDED_350: 350,
    keyboards.PAYLOAD_WATER_EXTENDED_750: 750,
    keyboards.PAYLOAD_WATER_EXTENDED_1500: 1500,
}


@router.message_callback(F.callback.payload.in_(set(_PAYLOAD_TO_ML.keys())))
async def on_water_add_quick(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """Click [+200/+250/+500/+1000 мл] (или extended) → POST add_water."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return
    payload = callback.callback.payload or ""
    ml = _PAYLOAD_TO_ML.get(payload)
    if ml is None:
        return

    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)
    extid = external_user_id_for(bot_user)

    # Idempotency-key derived from extid + ml + (timestamp в секундах)
    # — реклик в течение того же ts даёт same key, повторный POST cached.
    idem = str(uuid.uuid5(
        uuid.NAMESPACE_OID,
        f"{extid}:water:{ml}:{int(time.time())}",
    ))

    client = get_nutrition_client()
    try:
        entry = await client.add_water(
            external_user_id=extid,
            ml=ml,
            idempotency_key=idem,
        )
    except NutritionUnavailableError:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Учёт воды временно недоступен. Попробуй через минуту.",
        )
        return
    except NutritionAPIError as exc:
        logger.exception("water.add.api_error user=%s ml=%d err=%s",
                         bot_user.max_user_id, ml, exc)
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Не получилось записать. Попробуй ещё раз.",
        )
        return

    text = ai_ui.render_water_added(entry)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.water_undo_keyboard(entry_id=entry.entry_id)],
    )


@router.message_callback(F.callback.payload.startswith(keyboards.PAYLOAD_WATER_UNDO_PREFIX))
async def on_water_undo(callback: MessageCallback, context: MemoryContext) -> None:
    """[↩️ Отменить] → DELETE undo_water. 15-минутное window server-side."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return

    payload = callback.callback.payload or ""
    if not payload.startswith(keyboards.PAYLOAD_WATER_UNDO_PREFIX):
        return
    entry_id = payload[len(keyboards.PAYLOAD_WATER_UNDO_PREFIX):]
    if not entry_id:
        return

    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)

    client = get_nutrition_client()
    try:
        deleted = await client.undo_water(
            external_user_id=external_user_id_for(bot_user),
            entry_id=entry_id,
        )
    except NutritionUnavailableError:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Сервис недоступен — попробуй отменить через минуту.",
        )
        return
    except NutritionAPIError as exc:
        logger.exception("water.undo.api_error user=%s entry=%s err=%s",
                         bot_user.max_user_id, entry_id, exc)
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Не получилось отменить. Попробуй ещё раз.",
        )
        return

    if deleted:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="↩️ Отменила запись — удалила из дневника.",
        )
    else:
        await callback.bot.send_message(
            chat_id=chat_id,
            text=(
                "Поздно — запись уже зафиксирована (прошло больше "
                "15 минут). Если ошибка существенна — добавь "
                "противоположный объём вручную."
            ),
        )


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_WATER_MORE)
async def on_water_more(callback: MessageCallback, context: MemoryContext) -> None:
    """[✏️ Другое] → расширенный keyboard с 150/300/350/750/1500 мл."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Выбери объём:",
        attachments=[keyboards.water_extended_keyboard()],
    )


@router.message_created(
    F.message.body.text.lower().in_(("/вода", "/water", "вода")),
)
async def on_water_command(event: MessageCreated, context: MemoryContext) -> None:
    """`/вода` text command → status + amount keyboard.

    То же поведение что on_water_menu (callback) — pattern скопирован
    из food_scanner.on_diary_command.
    """
    if event.message.sender is None:
        return
    chat_id = event.message.recipient.chat_id

    if not getattr(django_settings, "NUTRITION_ENABLED", False):
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "💧 Учёт воды скоро добавлю — фича в разработке. "
                "Когда подключим — будешь следить за нормой воды и напитков."
            ),
        )
        return

    state = await context.get_state()
    if state is not None and str(state).startswith("NutritionAnketaStates"):
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Сейчас отвечаю на вопросы анкеты — "
                "пришли число / нажми кнопку, чтобы продолжить."
            ),
        )
        return

    user_id = event.message.sender.user_id
    full_name = event.message.sender.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)

    client = get_nutrition_client()
    try:
        today = await client.get_water_today(
            external_user_id=external_user_id_for(bot_user),
        )
    except NutritionUnavailableError:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Учёт воды временно недоступен. Попробуй через минуту.",
        )
        return
    except NutritionAPIError as exc:
        logger.exception("water.command.api_error user=%s err=%s",
                         bot_user.max_user_id, exc)
        await event.bot.send_message(
            chat_id=chat_id,
            text="Не получилось загрузить статус.",
        )
        return

    text = ai_ui.render_water_status(today)
    await event.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.water_amount_keyboard()],
    )
