"""Routers handler'ов MAX-бота.

main.py импортит get_routers() и регистрирует через dp.include_routers(*).
Каждый сценарий — свой Router в отдельном файле.
"""
from __future__ import annotations

from .ai_assistant import router as ai_assistant_router
from .booking import router as booking_router
from .contacts import router as contacts_router
from .fallback import router as fallback_router
from .faq import router as faq_router
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
        ai_assistant_router,
        fallback_router,
    ]
