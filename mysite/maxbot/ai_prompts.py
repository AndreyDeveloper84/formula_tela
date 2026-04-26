"""System prompt для AI Concierge — Phase 2.3.

См. docs/plans/maxbot-phase2-native-booking.md §T05.
Базируется на Ayla/djangoproject/ai/prompts.py.

Заменяет константу `texts.AI_SYSTEM_PROMPT` (которая для chat_rag — оставляем
её там для warmup и legacy chat_rag).

Цель: короткий (<500 токенов) prompt с правилами + контекстом мастеров.
gpt-4o-mini лучше следует коротким prompt'ам, и каждый system token =
оплачиваемый input.

TODO Phase 2.3 T05:
- SYSTEM_PROMPT_TEMPLATE с {today} {client_name} {bookings_count}
  {masters_summary} placeholders
- 11 правил (см. plan §T05)
- render_system_prompt(*, today, client_name, bookings_count, masters_summary) → str
- Unit-тесты на rendering с моками
"""
from __future__ import annotations

# Заглушка — детали будут в T05
SYSTEM_PROMPT_TEMPLATE = """\
Ты — Алина, ассистент салона «Формула тела» в Пензе.
TODO: дописать в Phase 2.3 T05
"""
