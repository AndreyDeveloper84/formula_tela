"""Phase 3 T01/T04: Nutrition entry — экран приветствия дневника питания.

Точка входа: callback `cb:menu:nutrition` из main_menu_keyboard().

Flow:
1. Пользователь жмёт «🍎 Дневник питания» в главном меню.
2. Этот handler шлёт welcome screen с двумя кнопками:
   - «📸 Попробовать сразу» (T03/T07 — заглушка пока)
   - «📝 Настроить под себя (30 сек)» (T04 анкета — реализована)
3. on_start_anketa устанавливает state=awaiting_consent и шлёт дисклеймер 152-ФЗ.
   Остальные шаги FSM анкеты — в handlers/nutrition_anketa.py (Phase 3.1 Part 1).

Это маленький router потому что entry-screen самодостаточен и не хочется
смешивать его с food_scanner (там callback'и `cb:nutrition:consent:*` и
`cb:nutrition:log:*` уже жирные).
"""
from __future__ import annotations

import logging

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback

from maxbot import keyboards
from maxbot.states import NutritionAnketaStates


logger = logging.getLogger("maxbot.handlers.nutrition_entry")

router = Router()


WELCOME_TEXT = (
    "\U0001f34e Дневник питания\n\n"
    "Сфоткай еду — скажу калории, БЖУ "
    "и подскажу как сбалансировать.\n\n"
    "Чтобы считать норму под тебя "
    "(а не средние 2000 ккал) — ответь "
    "на 4 вопроса, 30 секунд."
)


STUB_TRY_NOW_TEXT = (
    "\U0001f4f8 Скоро добавим — пока в разработке.\n\n"
    "Сейчас можно записать фото блюда — я распознаю и посчитаю "
    "калории. Просто пришли фото в чат."
)


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_MENU_NUTRITION)
async def on_show_nutrition_welcome(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """Главный entry-screen дневника. Кликается из main_menu_keyboard()."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=WELCOME_TEXT,
        attachments=[keyboards.nutrition_welcome_keyboard()],
    )


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_NUTRITION_TRY_NOW)
async def on_try_now_stub(callback: MessageCallback, context: MemoryContext) -> None:
    """Заглушка для «Попробовать сразу» до завершения T03 (food scanner refactor)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(chat_id=chat_id, text=STUB_TRY_NOW_TEXT)


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_NUTRITION_START_ANKETA)
async def on_start_anketa(callback: MessageCallback, context: MemoryContext) -> None:
    """Запуск TIER-A анкеты — set state и шлём consent-экран."""
    from maxbot.handlers.nutrition_anketa import CONSENT_TEXT

    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    await context.set_state(NutritionAnketaStates.awaiting_consent)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=CONSENT_TEXT,
        attachments=[keyboards.anketa_consent_keyboard()],
    )
