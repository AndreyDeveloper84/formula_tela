"""Phase 3.1 Part 2A T01: action-row keyboard для footer scan-карточки.

`action_row_keyboard()` — узкий 3-button bar [📸 Фото][💧 Вода][📋 Меню].
Используется когда нужен минимум action-кнопок без полного main_menu.
"""
from __future__ import annotations


def test_action_row_keyboard_three_buttons():
    from maxbot.keyboards import (
        action_row_keyboard,
        PAYLOAD_MENU_NUTRITION,
        PAYLOAD_NUTRITION_ADD_WATER,
        PAYLOAD_MENU_BOOK,
    )

    kb = action_row_keyboard()
    payloads = _flatten_payloads(kb)
    assert PAYLOAD_MENU_NUTRITION in payloads
    assert PAYLOAD_NUTRITION_ADD_WATER in payloads
    assert PAYLOAD_MENU_BOOK in payloads or "cb:menu:open" in payloads


def _flatten_payloads(keyboard) -> set[str]:
    """Best-effort обход maxapi keyboard structure."""
    out: set[str] = set()
    rows = (
        getattr(getattr(keyboard, "payload", None), "buttons", None)
        or getattr(keyboard, "buttons", None)
        or getattr(keyboard, "rows", None)
        or []
    )
    for row in rows:
        for btn in row:
            payload = getattr(btn, "payload", None)
            if payload is None:
                callback = getattr(btn, "callback", None)
                payload = getattr(callback, "payload", None) if callback else None
            if payload:
                out.add(payload)
    return out
