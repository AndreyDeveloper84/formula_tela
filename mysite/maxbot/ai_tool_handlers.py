"""Tool-call handlers — валидация LLM args + формирование action_data.

См. docs/plans/maxbot-phase2-native-booking.md §T03.
Базируется на Ayla/djangoproject/ai/tools_handlers.py.

Handlers SIDE-EFFECT-FREE — только validate ID и load display data. Реальные
side effects (создание BookingRequest + YClients booking) происходят в
ai_action_service.py после явного клика клиентом [✅ Да].

Anti-hallucination: каждый handler фильтрует ID через
`context.candidate_ids` (set реальных ID из БД). Если LLM выдумал ID —
fallback на ask_clarification вместо raise.

TODO Phase 2.3 T03:
- _safe_int(value) — defensive cast
- _fallback_clarification(reason) — bounce-helper
- handle_show_masters(args, context) → ToolResult
- handle_show_slots(args) → ToolResult (требует YClients call для слотов)
- handle_confirm_booking(args) → ToolResult (validate slot ещё свободен)
- handle_show_my_bookings(args, bot_user) → ToolResult (YClients get_records)
- handle_ask_clarification(args) → ToolResult
- dispatch_tool_call(tool_call, context, bot_user) — главный диспетчер
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    """Что handler возвращает в AIConcierge для записи в Message.action_*"""

    action_type: str
    action_data: dict[str, Any]
