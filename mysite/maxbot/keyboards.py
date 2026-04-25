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
PAYLOAD_CONFIRM_YES = "cb:confirm:yes"
PAYLOAD_CONFIRM_NO = "cb:confirm:no"

PAYLOAD_SVC_PREFIX = "cb:svc:"
PAYLOAD_FAQ_PREFIX = "cb:faq:"
PAYLOAD_CAT_PREFIX = "cb:cat:"

# MAX API лимит: 30 рядов в inline keyboard (см. dev.max.ru/docs-api).
# Резервируем 1 ряд под кнопку «Назад» → 29 кнопок-контента max.
MAX_KEYBOARD_ROWS = 29


def main_menu_keyboard():
    """Главное меню — 4 кнопки в 2 ряда."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="📅 Записаться", payload=PAYLOAD_MENU_BOOK),
        CallbackButton(text="ℹ️ Услуги", payload=PAYLOAD_MENU_SERVICES),
    )
    builder.row(
        CallbackButton(text="📞 Контакты", payload=PAYLOAD_MENU_CONTACTS),
        CallbackButton(text="❓ Вопросы", payload=PAYLOAD_MENU_FAQ),
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
    """
    builder = InlineKeyboardBuilder()
    for art in articles:
        builder.row(
            CallbackButton(text=art.question, payload=f"{PAYLOAD_FAQ_PREFIX}{art.id}"),
        )
    builder.row(CallbackButton(text="← Назад в меню", payload=PAYLOAD_BACK))
    return builder.as_markup()


def back_to_menu_keyboard() -> object:
    """Одна кнопка «← Назад в меню»."""
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="← Назад в меню", payload=PAYLOAD_BACK))
    return builder.as_markup()


def confirm_booking_keyboard() -> object:
    """Подтверждение/отмена заявки — 2 кнопки в ряду."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="✅ Да, всё верно", payload=PAYLOAD_CONFIRM_YES),
        CallbackButton(text="❌ Отмена", payload=PAYLOAD_CONFIRM_NO),
    )
    return builder.as_markup()
