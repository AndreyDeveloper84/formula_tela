"""Фабрики InlineKeyboard для MAX-бота.

Callback payload convention (см. tests/maxbot/test_keyboards.py docstring):
- cb:menu:{section}  — переход из главного меню
- cb:svc:{id}        — выбор услуги (id из services_app.Service)
- cb:faq:{id}        — выбор FAQ (id из services_app.HelpArticle)
- cb:back            — возврат в главное меню
- cb:confirm:{yes|no}— подтверждение/отмена заявки в FSM booking
"""
from __future__ import annotations

from typing import Iterable

from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

# Префиксы — единственное место где они объявлены, handlers импортят отсюда
PAYLOAD_MENU_BOOK = "cb:menu:book"
PAYLOAD_MENU_SERVICES = "cb:menu:services"
PAYLOAD_MENU_CONTACTS = "cb:menu:contacts"
PAYLOAD_MENU_FAQ = "cb:menu:faq"
PAYLOAD_BACK = "cb:back"
PAYLOAD_MENU_ASK = "cb:menu:ask"  # Кнопка «❓ Задать вопрос» (T-06c)
PAYLOAD_MENU_MY_BOOKINGS = "cb:menu:my_bookings"  # Кнопка «📋 Мои записи»
PAYLOAD_MENU_NUTRITION = "cb:menu:nutrition"  # Кнопка «🍎 Дневник питания» (Phase 3 T01)
PAYLOAD_NUTRITION_TRY_NOW = "cb:nutrition:try_now"  # «📸 Попробовать сразу» (Phase 3)
PAYLOAD_NUTRITION_START_ANKETA = "cb:nutrition:start_anketa"  # «📝 Настроить под себя» (Phase 3)
PAYLOAD_CONFIRM_YES = "cb:confirm:yes"
PAYLOAD_CONFIRM_NO = "cb:confirm:no"
PAYLOAD_CONFIRM_OTHER = "cb:confirm:other"  # «Указать другие данные» — сбросить FSM

PAYLOAD_SVC_PREFIX = "cb:svc:"
PAYLOAD_FAQ_PREFIX = "cb:faq:"
PAYLOAD_CAT_PREFIX = "cb:cat:"

# N2 — напоминания (BookingReminder.id в payload)
PAYLOAD_REM_CONFIRM_PREFIX = "cb:rem:confirm:"
PAYLOAD_REM_RESCHEDULE_PREFIX = "cb:rem:reschedule:"
PAYLOAD_REM_CANCEL_PREFIX = "cb:rem:cancel:"

# MAX API лимит: 30 рядов в inline keyboard (см. dev.max.ru/docs-api).
# Резервируем 1 ряд под кнопку «Назад» → 29 кнопок-контента max.
MAX_KEYBOARD_ROWS = 29


def main_menu_keyboard():
    """Главное меню — 7 кнопок в 5 рядов.

    Phase 3 T01: добавлена кнопка «🍎 Дневник питания» отдельным рядом
    между «Мои записи» и «Контакты». Inline keyboard через `attachments=`
    в каждом ответе — это «floating menu» паттерн (см. menu_state.py).
    Persistent reply-keyboard в MAX SDK не поддерживается — только inline.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="📅 Записаться", payload=PAYLOAD_MENU_BOOK),
        CallbackButton(text="ℹ️ Услуги", payload=PAYLOAD_MENU_SERVICES),
    )
    builder.row(
        CallbackButton(text="📋 Мои записи", payload=PAYLOAD_MENU_MY_BOOKINGS),
    )
    builder.row(
        CallbackButton(text="🍎 Дневник питания", payload=PAYLOAD_MENU_NUTRITION),
    )
    builder.row(
        CallbackButton(text="📞 Контакты", payload=PAYLOAD_MENU_CONTACTS),
        CallbackButton(text="❓ Вопросы", payload=PAYLOAD_MENU_FAQ),
    )
    builder.row(
        CallbackButton(text="💬 Задать вопрос", payload=PAYLOAD_MENU_ASK),
    )
    return builder.as_markup()


def nutrition_welcome_keyboard():
    """Welcome screen дневника питания — 2 кнопки.

    [📸 Попробовать сразу]   — degraded mode без анкеты (defaults норма)
    [📝 Настроить под себя]  — анкета FSM (T04)

    Phase 3 T01: обе кнопки сейчас ведут на заглушки «Скоро будет»,
    реальные flow в T03 (food scanner refactor) и T04 (анкета).
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="📸 Попробовать сразу", payload=PAYLOAD_NUTRITION_TRY_NOW),
    )
    builder.row(
        CallbackButton(
            text="📝 Настроить под себя (30 сек)",
            payload=PAYLOAD_NUTRITION_START_ANKETA,
        ),
    )
    builder.row(
        CallbackButton(text="← Назад в меню", payload=PAYLOAD_BACK),
    )
    return builder.as_markup()


def categories_keyboard(categories: Iterable) -> object:
    """Список категорий по 1 в ряду + «Назад в главное меню».

    categories — iterable ServiceCategory-инстансов; используем .id и .name.
    Лимит MAX_KEYBOARD_ROWS = 29 → молча обрезаем (8 категорий — норма).
    """
    builder = InlineKeyboardBuilder()
    for cat in list(categories)[:MAX_KEYBOARD_ROWS]:
        builder.row(
            CallbackButton(text=cat.name, payload=f"{PAYLOAD_CAT_PREFIX}{cat.id}"),
        )
    builder.row(CallbackButton(text="← Назад в меню", payload=PAYLOAD_BACK))
    return builder.as_markup()


def services_keyboard(services: Iterable) -> object:
    """Список услуг внутри категории + «Назад к категориям».

    Лимит: MAX_KEYBOARD_ROWS=29 услуг + 1 ряд под «Назад» = 30 рядов
    (хард-лимит MAX API). Излишек обрезается.
    """
    builder = InlineKeyboardBuilder()
    for svc in list(services)[:MAX_KEYBOARD_ROWS]:
        builder.row(
            CallbackButton(text=f"💆 {svc.name}", payload=f"{PAYLOAD_SVC_PREFIX}{svc.id}"),
        )
    builder.row(CallbackButton(text="← Категории", payload=PAYLOAD_MENU_SERVICES))
    return builder.as_markup()


def faq_keyboard(articles: Iterable) -> object:
    """Список FAQ-статей по 1 в ряду + «Назад».

    articles — iterable HelpArticle, используем .id и .question.
    Лимит MAX_KEYBOARD_ROWS=29 + 1 ряд под Назад = 30 (хард-лимит MAX API).
    На 168 статьях обрезается; полный список ищется через RAG (T-05+).
    """
    builder = InlineKeyboardBuilder()
    for art in list(articles)[:MAX_KEYBOARD_ROWS]:
        # MAX лимит на text кнопки — обрезаем длинные question (>64 chars)
        text = art.question if len(art.question) <= 64 else art.question[:61] + "…"
        builder.row(
            CallbackButton(text=text, payload=f"{PAYLOAD_FAQ_PREFIX}{art.id}"),
        )
    builder.row(CallbackButton(text="← Назад в меню", payload=PAYLOAD_BACK))
    return builder.as_markup()


def back_to_menu_keyboard() -> object:
    """Одна кнопка «← Назад в меню»."""
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="← Назад в меню", payload=PAYLOAD_BACK))
    return builder.as_markup()


def reminder_24h_keyboard(reminder_id: str) -> object:
    """3 кнопки для T-24h напоминания: Подтверждаю / Перенести / Отменить."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="✅ Подтверждаю",
            payload=f"{PAYLOAD_REM_CONFIRM_PREFIX}{reminder_id}",
        ),
    )
    builder.row(
        CallbackButton(
            text="🔄 Перенести",
            payload=f"{PAYLOAD_REM_RESCHEDULE_PREFIX}{reminder_id}",
        ),
        CallbackButton(
            text="❌ Отменить",
            payload=f"{PAYLOAD_REM_CANCEL_PREFIX}{reminder_id}",
        ),
    )
    return builder.as_markup()


def confirm_booking_keyboard(*, with_other: bool = False) -> object:
    """Подтверждение/отмена заявки.

    with_other=True добавляет кнопку «📝 Указать другие данные» — для сценария
    повторной записи где бот предлагает использовать сохранённые имя/телефон.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="✅ Да, всё верно", payload=PAYLOAD_CONFIRM_YES),
        CallbackButton(text="❌ Отмена", payload=PAYLOAD_CONFIRM_NO),
    )
    if with_other:
        builder.row(
            CallbackButton(text="📝 Указать другие данные", payload=PAYLOAD_CONFIRM_OTHER),
        )
    return builder.as_markup()
