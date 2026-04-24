"""Routers handler'ов MAX-бота.

main.py импортит get_routers() и регистрирует через dp.include_routers(*).
Каждый сценарий — свой Router в отдельном файле.
"""
from __future__ import annotations

from .start import router as start_router


def get_routers():
    """Возвращает список всех Router'ов в порядке регистрации.

    Порядок важен для фильтров — более специфичные handler'ы должны быть
    зарегистрированы раньше общих fallback'ов (T-12 fallback router идёт
    последним).
    """
    return [start_router]
