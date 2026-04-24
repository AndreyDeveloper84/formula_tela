"""Routers handler'ов MAX-бота.

main.py импортит get_routers() и регистрирует через dp.include_routers(*).
Каждый сценарий — свой Router в отдельном файле.
"""
from __future__ import annotations

from .booking import router as booking_router
from .contacts import router as contacts_router
from .fallback import router as fallback_router
from .faq import router as faq_router
from .services import router as services_router
from .start import router as start_router


def get_routers():
    """Возвращает список всех Router'ов в порядке регистрации.

    Порядок важен для фильтров — более специфичные handler'ы должны быть
    зарегистрированы раньше общих fallback'ов. fallback_router ВСЕГДА
    последним — он ловит весь не-matched text input.
    """
    return [
        start_router,
        services_router,
        booking_router,
        contacts_router,
        faq_router,
        fallback_router,
    ]
