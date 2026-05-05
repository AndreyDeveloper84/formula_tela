"""Scan correction handlers (Phase 3.1 Part 2A T07-T11).

Triggers (cb:scan:correct:* и related payloads):
- `cb:scan:correct:menu:{scan_id}` — открыть menu коррекции (T07)
- `cb:scan:correct:portion:menu` — открыть размер-portion submenu (T08)
- `cb:scan:correct:portion:smaller|normal|larger` — пересчитать порцию (T08, MVP-stub)
- `cb:scan:correct:other_dish` / `add_ingredient` / `delete` — заглушки (T09)
- `cb:scan:retake` / `cb:scan:manual` — переснять / ввести вручную (T09)
- `cb:nutrition:view_day` — daily_summary через эту cb (T11)

Отдельный router потому что food_scanner.py уже жирный (capture +
consent + meal-log) — добавлять correction туда увеличило бы файл вдвое.
"""
from __future__ import annotations

import logging

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback

from maxbot import ai_ui, keyboards
from maxbot.personalization import get_or_create_bot_user
from maxbot.services.ayla_user_proxy import external_user_id_for
from maxbot.services.nutrition_client import (
    NutritionAPIError,
    NutritionUnavailableError,
    get_nutrition_client,
)


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
    F.callback.payload == keyboards.PAYLOAD_NUTRITION_VIEW_DAY,
)
async def on_view_day(callback: MessageCallback, context: MemoryContext) -> None:
    """[📊 Посмотреть день] из footer scan-карточки → hybrid daily report
    (Part 2C: daily_summary + get_water_today + render_daily_full_report)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return
    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)

    extid = external_user_id_for(bot_user)
    client = get_nutrition_client()

    # Fetch both summary + water — water optional (graceful skip)
    try:
        summary = await client.daily_summary(external_user_id=extid)
    except NutritionUnavailableError:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Дневник временно недоступен. Попробуй через минуту.",
        )
        return
    except NutritionAPIError as exc:
        logger.exception("food_correction.summary.api_error user=%s err=%s",
                         bot_user.max_user_id, exc)
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Не получилось загрузить дневник.",
        )
        return

    water_today = None
    try:
        water_today = await client.get_water_today(external_user_id=extid)
    except (NutritionUnavailableError, NutritionAPIError):
        # Water optional — silently skip раздел
        logger.info("food_correction.view_day water unavailable for user=%s",
                    bot_user.max_user_id)

    eating_disorder = bool(
        (bot_user.health_flags or {}).get("eating_disorder", False)
    )
    text = ai_ui.render_daily_full_report(
        summary, water_today, eating_disorder=eating_disorder,
    )
    await callback.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.daily_report_footer_keyboard()],
    )


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_REPORT_WEEKLY,
)
async def on_report_weekly_stub(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[📊 Неделя] — заглушка Phase 3.3 (требует tracking 7-day FoodEntry streak)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "📊 Недельный отчёт Скоро добавлю — нужно собрать данные за "
            "7 дней с записями. Продолжай вести дневник, и через неделю "
            "покажу тренды."
        ),
    )


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_REPORT_TIME_SETTINGS,
)
async def on_report_time_settings_stub(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[⚙️ Время отчёта] — заглушка Part 2D (требует user-settings UI)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "⚙️ Настройка времени отчёта Скоро будет — пока шлю в 21:00 "
            "по Москве. Если неудобно — напиши, скорректируем."
        ),
    )
