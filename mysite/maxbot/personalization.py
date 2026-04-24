"""Персонализация диалога: get_or_create_bot_user, greet_text, update_context.

Основа: services_app.BotUser. Все ORM-операции через sync_to_async — handler'ы
async, ORM sync.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async

from maxbot import texts


@sync_to_async
def get_or_create_bot_user(max_user_id: int, display_name: str = ""):
    """Возвращает (BotUser, created: bool).

    При повторном визите — обновляет display_name (от MAX) если он изменился,
    но НЕ перезаписывает client_name (который клиент сам ввёл боту).

    last_seen обновится автоматически через `auto_now=True` при сохранении.
    """
    from services_app.models import BotUser

    user, created = BotUser.objects.get_or_create(
        max_user_id=max_user_id,
        defaults={"display_name": display_name},
    )
    if not created:
        # update display_name (с MAX) если поменялся
        if display_name and user.display_name != display_name:
            user.display_name = display_name
            user.save(update_fields=["display_name", "last_seen"])
        else:
            # просто прокинуть last_seen
            user.save(update_fields=["last_seen"])
    return user, created


def greet_text(bot_user, *, is_new: bool) -> str:
    """Текст приветствия — персонализированный если есть имя."""
    if is_new:
        return texts.GREETING_NEW_USER

    name = bot_user.client_name or bot_user.display_name
    if name:
        return texts.GREETING_RETURNING.format(name=name)
    return texts.GREETING_NEW_USER


@sync_to_async
def update_context(bot_user_id: int, **updates) -> None:
    """Atomically merges kwargs в context dict. Перезаписывает существующие ключи."""
    from services_app.models import BotUser

    user = BotUser.objects.get(pk=bot_user_id)
    user.context.update(updates)
    user.save(update_fields=["context", "last_seen"])


@sync_to_async
def append_to_context(bot_user_id: int, key: str, value) -> None:
    """Добавить value в список под ключом key. Без дублей."""
    from services_app.models import BotUser

    user = BotUser.objects.get(pk=bot_user_id)
    lst = user.context.setdefault(key, [])
    if value not in lst:
        lst.append(value)
        user.save(update_fields=["context", "last_seen"])
