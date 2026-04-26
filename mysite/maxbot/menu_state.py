"""Управление состоянием главного меню — «плавающее меню» (Вариант B).

Цель: меню всегда висит у самого свежего бот-сообщения, никогда не
дублируется в чате. При отправке нового сообщения с главным меню —
старое меню снимается через `edit_message(attachments=[])`.

State хранится в `BotUser.context["last_main_menu_msg_id"]` +
`["last_main_menu_msg_text"]` (нужен текст т.к. edit_message требует text).

Race conditions: при concurrent сообщениях от одного user'а две handler'ы
могут одновременно прочитать тот же `last_main_menu_msg_id` и обе
попытаться edit + send. Edge case даёт максимум один лишний дубль
(редко). Не используем DB lock из-за async-вызовов внутри транзакции —
оставляем lockless для простоты, реальная нагрузка ~100 msg/day.

НЕ для контекстных клавиатур (categories/services/faq/booking-confirm) —
они быстро сменяются и tracking их через state — overkill.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.db import transaction

from maxbot import keyboards
from services_app.models import BotUser


logger = logging.getLogger("maxbot.menu")

CTX_LAST_MENU_MID = "last_main_menu_msg_id"
CTX_LAST_MENU_TEXT = "last_main_menu_msg_text"


@sync_to_async
def _save_menu_state(bot_user_id: int, msg_id: str, text: str) -> None:
    """Atomic update двух полей контекста — защита от race с другими update_context."""
    with transaction.atomic():
        user = BotUser.objects.select_for_update().get(pk=bot_user_id)
        user.context[CTX_LAST_MENU_MID] = msg_id
        user.context[CTX_LAST_MENU_TEXT] = text
        user.save(update_fields=["context", "last_seen"])


async def send_with_main_menu(
    *,
    bot,
    chat_id: int,
    text: str,
    bot_user: BotUser,
    extra_attachments: list | None = None,
) -> None:
    """Отправить сообщение с главным меню, сняв меню с предыдущего бот-ответа.

    Шаги:
    1. Прочитать `last_main_menu_msg_id` + `_text` из bot_user.context
    2. Если есть — edit_message(prev_id, text=prev_text, attachments=[])
       (best-effort, exception поглощается — msg могло быть удалено / устарело)
    3. send_message(text, attachments=[*extra_attachments, main_menu_keyboard()])
    4. Сохранить новый msg_id + text в bot_user.context (atomic)

    extra_attachments: например welcome-картинка для нового user'а — пойдёт
    ПЕРЕД меню (отображается над клавиатурой). Если None — только меню.

    Если `bot.send_message` упадёт — exception пропускается наверх.
    """
    prev_mid = bot_user.context.get(CTX_LAST_MENU_MID) if bot_user.context else None
    prev_text = bot_user.context.get(CTX_LAST_MENU_TEXT) if bot_user.context else None

    # 1. Снять меню с предыдущего сообщения (best-effort)
    if prev_mid and prev_text:
        try:
            await bot.edit_message(
                message_id=prev_mid,
                text=prev_text,
                attachments=[],
            )
        except Exception as exc:  # noqa: BLE001
            # Сообщение могло быть удалено клиентом / устарело / network issue —
            # не блокируем отправку нового. Один лишний дубль в чате — terpимо.
            logger.warning("edit_message(prev menu) failed: %s", exc)

    # 2. Отправить новое сообщение с меню (+ опциональные attachments перед ним)
    attachments = list(extra_attachments) if extra_attachments else []
    attachments.append(keyboards.main_menu_keyboard())
    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=attachments,
    )

    # 3. Сохранить state — берём mid из ответа MAX
    new_mid = _extract_message_id(sent)
    if new_mid is None:
        logger.warning("send_message returned without mid; menu state not updated")
        return
    await _save_menu_state(bot_user.id, new_mid, text)
    # Sync in-memory копию для caller'а (на случай если bot_user используется дальше)
    if bot_user.context is None:
        bot_user.context = {}
    bot_user.context[CTX_LAST_MENU_MID] = new_mid
    bot_user.context[CTX_LAST_MENU_TEXT] = text


def _extract_message_id(sent) -> str | None:
    """Достаёт mid из ответа send_message. SDK обёртка типа SendedMessage.

    Возвращает только если mid — реальная строка, иначе None. Защита от
    тестовых MagicMock'ов, у которых getattr(body, "mid") возвращает не None.
    """
    if sent is None:
        return None
    for path in (("body", "mid"), ("message", "body", "mid")):
        node = sent
        for attr in path:
            node = getattr(node, attr, None)
            if node is None:
                break
        if isinstance(node, str) and node:
            return node
    return None
