"""ActionService — обрабатывает callback'и confirm/pick/cancel + booking creation.

См. docs/plans/maxbot-phase2-native-booking.md §T09.
Базируется на Ayla/djangoproject/ai/application/services/action_service.py.

execute_confirm_booking(conversation):
1. Загрузить последний Message с action_type=confirm_booking + action_data
2. Idempotency check: cache.get(f"ai-{conversation.id}")
3. YClientsAPI.create_booking(staff_id, service_id, datetime, phone, name)
4. Save BookingRequest(source='bot_max', yclients_record_id=...)
5. Telegram админу
6. save Message(role=tool)
7. Закрыть conversation
8. Return success message

Graceful degradation:
- YClients API down → BookingRequest без yclients_record_id +
  requires_manual_booking=True
- Telegram админу с детальной формой
- Клиенту: «Менеджер свяжется в течение часа»

TODO Phase 2.3 T09:
- _load_last_confirm_action(conversation) — query Message
- _create_yclients_booking(action_data, bot_user) → record_id
- _create_booking_request(...) — создание BookingRequest
- _close_conversation(conv)
- ActionResultDTO с success + booking_id + error_code
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActionResultDTO:
    success: bool
    booking_request_id: int | None
    yclients_record_id: str | None
    error_code: str | None = None
    error_details: dict[str, Any] | None = None
