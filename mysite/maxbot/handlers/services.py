"""Handler «Услуги» — каталог + клик на услугу → старт FSM заявки.

Сценарий:
1. cb:menu:services       → on_show_services    → клавиатура из Service.objects.active()
2. cb:svc:{id}            → on_pick_service     → FSM awaiting_name + "Как к вам обращаться?"
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback

from maxbot import keyboards, texts
from maxbot.personalization import append_to_context, get_or_create_bot_user
from maxbot.states import BookingStates
from services_app.models import Service


logger = logging.getLogger("maxbot.services")
router = Router()


@sync_to_async
def _list_active_services() -> list[Service]:
    """Active услуги, материализованный список (callable из async-handler'а)."""
    return list(Service.objects.active().order_by("name"))


@sync_to_async
def _get_service_or_none(service_id: int) -> Service | None:
    return Service.objects.filter(id=service_id, is_active=True).first()


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_MENU_SERVICES)
async def on_show_services(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    services = await _list_active_services()
    if services:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Выберите услугу для записи:",
            attachments=[keyboards.services_keyboard(services)],
        )
    else:
        # Fallback на случай пустого каталога — не должно случиться в проде, но защита
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Сейчас услуги не настроены. Позвоните по телефону из «Контакты».",
            attachments=[keyboards.back_to_menu_keyboard()],
        )


@router.message_callback(F.callback.payload.startswith(keyboards.PAYLOAD_SVC_PREFIX))
async def on_pick_service(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    # Парсим id из payload "cb:svc:123"
    payload = callback.callback.payload or ""
    raw_id = payload[len(keyboards.PAYLOAD_SVC_PREFIX):]
    try:
        service_id = int(raw_id)
    except ValueError:
        logger.warning("on_pick_service: некорректный payload %r", payload)
        return

    svc = await _get_service_or_none(service_id)
    if svc is None:
        logger.warning("on_pick_service: Service id=%s не найден или не активен", service_id)
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Услуга больше недоступна. Выберите из главного меню.",
            attachments=[keyboards.back_to_menu_keyboard()],
        )
        return

    # Сохраняем в FSM выбранную услугу + переходим в awaiting_name
    await context.set_state(BookingStates.awaiting_name)
    await context.update_data(service_id=svc.id, service_name=svc.name)

    # Логируем в context BotUser (для персонализации в будущем)
    user = callback.callback.user
    bot_user, _ = await get_or_create_bot_user(user.user_id, user.full_name)
    await append_to_context(bot_user.id, "services_viewed", svc.slug)

    await callback.bot.send_message(
        chat_id=chat_id,
        text=texts.BOOKING_ASK_NAME,
    )
