"""Scan correction handlers (Phase 3.1 Part 2A T07-T11).

Triggers (cb:scan:correct:* и related payloads):
- `cb:scan:correct:menu:{scan_id}` — открыть menu коррекции (T07)
- `cb:scan:correct:portion:menu` — открыть размер-portion submenu (T08)
- `cb:scan:correct:portion:smaller|normal|larger` — пересчитать порцию (T08, MVP-stub)
- `cb:scan:correct:other_dish` / `add_ingredient` / `delete` — заглушки (T09)
- `cb:scan:retake` / `cb:scan:manual` — переснять / ввести вручную (T09)
- `cb:nutrition:water:add` — заглушка до Part 2B (T10)
- `cb:nutrition:view_day` — daily_summary через эту cb (T11)

Отдельный router потому что food_scanner.py уже жирный (capture +
consent + meal-log) — добавлять correction туда увеличило бы файл вдвое.
"""
from __future__ import annotations

import logging

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback

from maxbot import keyboards


logger = logging.getLogger("maxbot.handlers.food_correction")
router = Router()


CORRECT_MENU_TEXT = "🤖 Что не так с распознаванием?"


@router.message_callback(F.callback.payload.startswith("cb:scan:correct:menu"))
async def on_correct_open_menu(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[✏️ Поправить] на scan-карточке → открыть menu.

    Payload format: `cb:scan:correct:menu:{scan_id}`. scan_id пока не
    используется (menu без scan-context), но extract'ится для T08+
    portion-recalc.
    """
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=CORRECT_MENU_TEXT,
        attachments=[keyboards.food_scan_correct_menu_keyboard()],
    )


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_PORTION_OPEN_MENU,
)
async def on_portion_menu(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[📦 Размер порции] → показать [Меньше][Норм][Больше].

    Phase 3.2: связать с фактическим scan_id для пересчёта через
    scan_photo(portion_multiplier=...). Сейчас MVP — просто меню
    показываем; пересчёт не делаем (требует storage scan↔image).
    """
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="📦 Какого размера порция?",
        attachments=[keyboards.food_scan_portion_keyboard()],
    )


@router.message_callback(
    F.callback.payload.in_({
        keyboards.PAYLOAD_SCAN_PORTION_SMALLER,
        keyboards.PAYLOAD_SCAN_PORTION_NORMAL,
        keyboards.PAYLOAD_SCAN_PORTION_LARGER,
    }),
)
async def on_portion_apply(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[Меньше][Норм][Больше] — Phase 3.2 пересчёт через scan_photo
    с portion_multiplier=0.7/1.0/1.3. MVP — заглушка.

    Полноценная реализация требует хранить scan_id ↔ image_bytes (или
    URL) чтобы можно было пересчитать. Сейчас Ayla scan не возвращает
    image_url, и бот не хранит bytes. Backlog Phase 3.2.
    """
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "🔧 Пересчёт порции скоро добавлю — пока пришли фото снова "
            "с правильной порцией в кадре."
        ),
    )


COMING_SOON_PHASE32 = (
    "🔧 Скоро добавлю — пока в разработке (Phase 3.2). "
    "Пришли фото снова или впиши блюдо текстом."
)


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_OTHER_DISH,
)
async def on_other_dish(callback: MessageCallback, context: MemoryContext) -> None:
    """[🔄 Это другое блюдо] — заглушка Phase 3.2 (требует new Ayla endpoint
    для override-scan с caption: 'это был ризотто')."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(chat_id=chat_id, text=COMING_SOON_PHASE32)


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_ADD_INGREDIENT,
)
async def on_add_ingredient(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[➕ Добавить ингредиент] — заглушка Phase 3.2."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(chat_id=chat_id, text=COMING_SOON_PHASE32)


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_DELETE,
)
async def on_delete_log(callback: MessageCallback, context: MemoryContext) -> None:
    """[⏭ Удалить] — заглушка Phase 3.2 (требует new Ayla endpoint
    DELETE /food-log/{id}/)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(chat_id=chat_id, text=COMING_SOON_PHASE32)


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_RETAKE,
)
async def on_retake(callback: MessageCallback, context: MemoryContext) -> None:
    """[📸 Переснять] — попроси прислать новое фото."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="📸 Пришли фото блюда ещё раз — попробую распознать получше.",
    )


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_MANUAL_INPUT,
)
async def on_manual_input(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[✏️ Напишу сама] — заглушка Phase 3.2 (free-text + GPT-парсинг)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(chat_id=chat_id, text=COMING_SOON_PHASE32)


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_NUTRITION_ADD_WATER,
)
async def on_add_water_stub(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[💧 Добавить воду] из footer — заглушка до Part 2B.

    Реальный handler в `mysite/maxbot/handlers/water.py` (Part 2B).
    После создания того модуля — этот handler удаляется (или его router
    регистрируется ПОСЛЕ water_router чтобы не перехватывать).
    """
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "💧 Учёт воды скоро добавлю — фича в разработке (Part 2B). "
            "Пока можешь пометить себе вручную."
        ),
    )
