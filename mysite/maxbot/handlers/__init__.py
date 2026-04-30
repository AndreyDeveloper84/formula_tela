"""Routers handler'ов MAX-бота.

main.py импортит get_routers() и регистрирует через dp.include_routers(*).
Каждый сценарий — свой Router в отдельном файле.
"""
from __future__ import annotations

from .ai_assistant import router as ai_assistant_router
from .ai_callbacks import router as ai_callbacks_router
from .booking import router as booking_router
from .contacts import router as contacts_router
from .fallback import router as fallback_router
from .faq import router as faq_router
from .food_scanner import router as food_scanner_router
from .reminders import router as reminders_router
from .services import router as services_router
from .start import router as start_router


def get_routers():
    """Возвращает список всех Router'ов в порядке регистрации.

    Порядок важен для фильтров — более специфичные handler'ы должны быть
    зарегистрированы раньше общих fallback'ов.

    Структура (T-06c):
    - start/services/booking/contacts/faq — кнопочные сценарии (specific
      callbacks или state-фильтры BookingStates.X для FSM-вводов)
    - ai_assistant — БЕЗ state-фильтра, ловит всё остальное (free-text,
      AskStates.awaiting_question)
    - fallback — резервный для edge-case'ов (системные сообщения без sender)
    """
    return [
        start_router,
        services_router,
        booking_router,
        contacts_router,
        faq_router,
        # reminders ПЕРЕД ai_callbacks/ai_assistant — cb:rem:* должны матчиться
        # раньше generic message_created (N2).
        reminders_router,
        # ai_callbacks ПЕРЕД ai_assistant — специфичные cb:ai:* callbacks
        # должны матчиться раньше общего message_created handler'а.
        ai_callbacks_router,
        # food_scanner ПЕРЕД ai_assistant — оба ловят message_created, но
        # food_scanner early-return'ит если у сообщения нет фото-вложения,
        # передавая управление дальше. cb:nutrition:* callbacks тоже здесь.
        food_scanner_router,
        ai_assistant_router,
        fallback_router,
    ]
