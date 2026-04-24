"""Персонализация диалога: get_or_create_bot_user, greet_text, update_context.

Основа: services_app.BotUser. Все ORM-операции через sync_to_async — handler'ы
async, ORM sync. Конкурентные обновления context защищены через
transaction.atomic + select_for_update (один webhook на user обычно
сериализуется MAX-ом, но при ретраях/быстрых double-tap'ах race возможен).
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from maxbot import texts
from services_app.models import BotUser


@sync_to_async
def get_or_create_bot_user(max_user_id: int, display_name: str = ""):
    """Возвращает (BotUser, created: bool).

    Для existing user — атомарный UPDATE одной командой (не save!) — экономит
    1 query на hot path /start. Не перезаписывает client_name (его клиент
    ввёл боту, а display_name приходит от MAX автоматически).
    """
    user, created = BotUser.objects.get_or_create(
        max_user_id=max_user_id,
        defaults={"display_name": display_name},
    )
    if not created:
        # Один UPDATE вместо обращения user.save() — нет re-fetch, нет race на других полях.
        update_kwargs = {"last_seen": timezone.now()}
        if display_name and user.display_name != display_name:
            update_kwargs["display_name"] = display_name
            user.display_name = display_name  # Sync in-memory копию для caller'а
        BotUser.objects.filter(pk=user.pk).update(**update_kwargs)
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
    """Atomic merge updates в context dict (защита от race при concurrent webhook'ах)."""
    with transaction.atomic():
        user = BotUser.objects.select_for_update().get(pk=bot_user_id)
        user.context.update(updates)
        user.save(update_fields=["context", "last_seen"])


@sync_to_async
def append_to_context(bot_user_id: int, key: str, value) -> None:
    """Atomic append value в список под ключом key. Без дублей."""
    with transaction.atomic():
        user = BotUser.objects.select_for_update().get(pk=bot_user_id)
        lst = user.context.setdefault(key, [])
        if value not in lst:
            lst.append(value)
            user.save(update_fields=["context", "last_seen"])
