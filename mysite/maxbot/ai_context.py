"""Master context builder для system_prompt'а AI Concierge.

См. docs/plans/maxbot-phase2-native-booking.md §T04.
Базируется на Ayla/djangoproject/ai/application/services/specialist_context_builder.py.

Цель: на каждом chat_message собрать Top-N активных мастеров с их услугами,
отрендерить в текст для system_prompt'а. Включить set реальных ID для
anti-hallucination фильтра в tool_handlers.

build_master_context() →
  MasterContext(
      candidates=[(master, services)],     # detailed objects
      candidate_ids={42, 43, 44, ...},     # int set для O(1) проверки
      summary_text="...",                   # текст для system_prompt
  )

TODO Phase 2.3 T04:
- @dataclass MasterContext
- _summary_text() — render N мастеров строкой ≤500 токенов
- build_master_context() async ORM-query (Master.objects.active().prefetch...)
- Сортировка: rating DESC, experience DESC, name ASC
- Limit: 20 мастеров (текущий салон вряд ли больше)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MasterContext:
    """Bundle мастеров + their услуг для system_prompt'а LLM."""

    candidates: list  # list of Master ORM objects with prefetched services
    candidate_ids: frozenset  # int set для anti-hallucination check в handlers
    summary_text: str  # отрендеренный markdown для prompt'а
