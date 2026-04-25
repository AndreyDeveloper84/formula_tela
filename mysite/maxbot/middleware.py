"""Middleware MAX-бота: логирование + Telegram-алерты на handler-exceptions.

Регистрируется в main.py через `dp.middlewares = [...]`.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from maxapi.filters.middleware import BaseMiddleware
from maxapi.types import UpdateUnion
from notifications import send_notification_telegram


logger = logging.getLogger("maxbot.middleware")


class LoggingMiddleware(BaseMiddleware):
    """Логирует тип события + user_id для каждой обработки."""

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event_object: UpdateUnion,
        data: Dict[str, Any],
    ) -> Any:
        update_type = getattr(event_object, "update_type", "?")
        try:
            user_id = getattr(event_object, "from_user", None)
            user_id = user_id.user_id if user_id else "?"
        except Exception:
            user_id = "?"
        logger.info("MAX event: type=%s user_id=%s", update_type, user_id)
        return await handler(event_object, data)


class ErrorAlertMiddleware(BaseMiddleware):
    """Ловит exception от handler'а → лог + Telegram-алерт + re-raise.

    Re-raise оставлен намеренно: dispatcher SDK сам решает что делать
    (обычно — log + не падать), а мы получаем алерт менеджеру.
    """

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event_object: UpdateUnion,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event_object, data)
        except Exception as exc:
            update_type = getattr(event_object, "update_type", "?")
            logger.exception("MAX handler crashed: type=%s exc=%r", update_type, exc)
            try:
                send_notification_telegram(
                    f"⚠️ MAX-бот: handler упал\n"
                    f"Тип события: {update_type}\n"
                    f"Ошибка: {type(exc).__name__}: {exc}"
                )
            except Exception:  # noqa: BLE001
                logger.exception("Не удалось отправить Telegram-алерт об ошибке handler-а")
            raise
