"""OpenAI tool definitions для AI Concierge — Phase 2.3.

См. docs/plans/maxbot-phase2-native-booking.md §T02.
Базируется на Ayla/djangoproject/ai/tools.py (адаптация UUID→int, термины).

Эти схемы передаются в `chat.completions.create(tools=[...])`. LLM
эмиттит tool_call с одной из этих shapes; ai_tool_handlers.py валидирует
args и формирует action_data.

5 tools в MVP. show_masters / show_slots / confirm_booking /
show_my_bookings / ask_clarification.

TODO Phase 2.3 T02:
- Определить SHOW_MASTERS, SHOW_SLOTS, CONFIRM_BOOKING, SHOW_MY_BOOKINGS,
  ASK_CLARIFICATION dict-схемы.
- TOOL_DEFINITIONS = [...] — список для передачи в OpenAI.
- ActionType class с константами имён (стабильный wire-format).
- Unit-тесты test_ai_tools_schemas.py — JSON-валидность каждой схемы.
"""
from __future__ import annotations

# Заглушка чтобы импорты при разработке работали
TOOL_DEFINITIONS: list[dict] = []


class ActionType:
    """Action types для action_data в Message.action_type. Wire-format.

    Имена должны 1:1 совпадать с function name в TOOL_DEFINITIONS — так
    LLM-emitter и DB-storage используют одну строку.
    """

    SHOW_MASTERS = "show_masters"
    SHOW_SLOTS = "show_slots"
    CONFIRM_BOOKING = "confirm_booking"
    SHOW_MY_BOOKINGS = "show_my_bookings"
    ASK_CLARIFICATION = "ask_clarification"

    ALL_MVP = frozenset({
        SHOW_MASTERS,
        SHOW_SLOTS,
        CONFIRM_BOOKING,
        SHOW_MY_BOOKINGS,
        ASK_CLARIFICATION,
    })
