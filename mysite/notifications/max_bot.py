"""Прямая отправка сообщений в MAX-бот через REST API (для админ-actions).

Зачем НЕ использовать maxapi SDK: это вызывается из Django admin (sync),
а maxapi асинхронный. Прямой POST через requests с тем же Bearer-token —
~10 строк, не требует лишних зависимостей.

Используется в `services_app.admin.BotInquiryAdmin.send_reply_to_client`
для T-09 push-back: менеджер пишет ответ в админке → action шлёт в MAX.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings


logger = logging.getLogger(__name__)


def send_max_message(*, chat_id: int, text: str, timeout: int = 10) -> bool:
    """Отправить text в MAX-чат через REST API.

    Returns True при HTTP 2xx. False — если token не задан или API упал
    (исключение НЕ пробрасывается — caller получит False и решит что делать).
    """
    token = getattr(settings, "MAX_BOT_TOKEN", "")
    if not token:
        logger.warning("send_max_message: MAX_BOT_TOKEN не задан")
        return False

    try:
        r = requests.post(
            "https://botapi.max.ru/messages",
            headers={"Authorization": token, "Content-Type": "application/json"},
            params={"chat_id": chat_id},
            json={"text": text},
            timeout=timeout,
        )
        if not r.ok:
            logger.warning(
                "send_max_message HTTP %s for chat_id=%s: %s",
                r.status_code, chat_id, r.text[:200],
            )
        return r.ok
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_max_message exception for chat_id=%s: %s", chat_id, exc)
        return False
