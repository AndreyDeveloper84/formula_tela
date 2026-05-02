"""Phase 3 T01: Nutrition entry — экран приветствия дневника питания.

Точка входа: callback `cb:menu:nutrition` из main_menu_keyboard().

Flow:
1. Пользователь жмёт «🍎 Дневник питания» в главном меню.
2. Этот handler шлёт welcome screen с двумя кнопками:
   - «📸 Попробовать сразу» (T03/T07 — заглушка пока)
   - «📝 Настроить под себя (30 сек)» (T04 анкета — заглушка пока)
3. Заглушки на try_now / start_anketa просто отвечают «Скоро будет» —
   реальные flow появятся в T03/T04.

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


logger = logging.getLogger("maxbot.handlers.nutrition_entry")

router = Router()


WELCOME_TEXT = (
    "🍎 Дневник питания\n\n"
    "Сфоткай еду — скажу калории, БЖУ "
    "и подскажу как сбалансировать.\n\n"
    "Чтобы считать норму под тебя "
    "(а не средние 2000 ккал) — ответь "
    "на 4 вопроса, 30 секунд."
)


STUB_TRY_NOW_TEXT = (
    "📸 Скоро добавим — пока в разработке.\n\n"
    "Сейчас можно записать фото блюда — я распознаю и посчитаю "
    "калории. Просто пришли фото в чат."
)


STUB_ANKETA_TEXT = (
    "📝 Анкета скоро появится — мы её сейчас собираем.\n\n"
    "Когда будет готова — посчитаю норму ккал и БЖУ под твои "
    "параметры (вес/рост/цель/здоровье)."
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
async def on_start_anketa_stub(callback: MessageCallback, context: MemoryContext) -> None:
    """Заглушка для «Настроить под себя» до завершения T04 (анкета FSM)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(chat_id=chat_id, text=STUB_ANKETA_TEXT)
