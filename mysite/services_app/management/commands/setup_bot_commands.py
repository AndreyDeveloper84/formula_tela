"""Регистрирует slash-меню MAX-бота через `Bot.set_my_commands`.

Без этого UI бота не показывает «Start»-кнопку при первом открытии чата
и пустое slash-меню — клиент не видит подсказок что можно сделать.

Запуск (один раз после деплоя или при изменении набора):
    python manage.py setup_bot_commands

Команды идемпотентны — каждый вызов перезаписывает набор полностью.
"""
from __future__ import annotations

import asyncio

from django.core.management.base import BaseCommand

from maxapi import Bot
from maxapi.types import BotCommand

from maxbot.config import get_config


COMMANDS: list[BotCommand] = [
    BotCommand(name="start", description="Главное меню"),
    BotCommand(name="services", description="Услуги и цены"),
    BotCommand(name="contacts", description="Контакты и адрес"),
    BotCommand(name="ask", description="Задать вопрос боту"),
]


class Command(BaseCommand):
    help = "Регистрирует slash-меню MAX-бота (видно как Start-кнопка при первом /start)."

    def handle(self, *args, **options):
        cfg = get_config()
        result = asyncio.run(_apply(cfg.token))
        self.stdout.write(self.style.SUCCESS(
            f"set_my_commands ok: {len(COMMANDS)} команд "
            f"({', '.join(f'/{c.name}' for c in COMMANDS)})"
        ))
        if result is not None:
            self.stdout.write(f"bot info: user_id={getattr(result, 'user_id', '?')}")


async def _apply(token: str):
    bot = Bot(token=token)
    try:
        return await bot.set_my_commands(*COMMANDS)
    finally:
        await bot.close_session()
