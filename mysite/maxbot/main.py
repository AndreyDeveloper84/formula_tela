"""MAX Bot entrypoint — отдельный async-процесс рядом с Django gunicorn'ом.

Запуск:
    python -m maxbot.main

Режимы (env MAX_BOT_MODE):
- polling — long-poll, для локалки/dev
- webhook — production за nginx

См. docs/plans/maxbot-phase1.md §4.1.
"""
from __future__ import annotations

import asyncio
import logging

# Django нужен ДО импорта handlers/ — те читают модели services_app.
from maxbot.django_bootstrap import setup_django
setup_django()

from maxapi import Bot, Dispatcher  # noqa: E402

from maxbot.config import get_config  # noqa: E402

logger = logging.getLogger("maxbot")


def build_dispatcher() -> Dispatcher:
    """Собирает Dispatcher с зарегистрированными handler'ами.

    На T-03 — пустой каркас (handler'ы добавим в T-07..T-12).
    """
    dp = Dispatcher()
    # T-07: dp.include_router(start.router)
    # T-08: dp.include_router(services.router)
    # ...
    return dp


async def run() -> None:
    cfg = get_config()
    bot = Bot(token=cfg.token)
    dp = build_dispatcher()

    me = await bot.get_me()
    logger.info("MAX bot online: user_id=%s username=%s", me.user_id, me.username)

    if cfg.mode == "polling":
        logger.info("Mode: long-polling")
        await bot.delete_webhook()
        await dp.start_polling(bot)
    else:
        logger.info(
            "Mode: webhook %s:%s path=%s secret=%s",
            cfg.webhook_host, cfg.webhook_port, cfg.webhook_path, bool(cfg.webhook_secret),
        )
        # secret=None если пустая строка → SDK не валидирует X-Max-Bot-Api-Secret
        await dp.handle_webhook(
            bot=bot,
            host=cfg.webhook_host,
            port=cfg.webhook_port,
            path=cfg.webhook_path,
            secret=cfg.webhook_secret or None,
        )


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    _configure_logging()
    asyncio.run(run())
