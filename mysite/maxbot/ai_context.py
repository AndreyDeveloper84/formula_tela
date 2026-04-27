"""Master context builder для system_prompt'а AI Concierge — Phase 2.3 §T04.

Адаптация Ayla/djangoproject/ai/application/services/specialist_context_builder.py.
Упрощения vs Ayla: single-salon (нет геолокации), нет min_rating filter,
нет distance ordering. Просто Top-N активных мастеров с услугами.

build_master_context() → MasterContext, который содержит:
- candidates: list[MasterCandidate] — id, name, specialization, services
- candidate_ids: frozenset[int] — для O(1) anti-hallucination check в handlers
- candidate_service_ids: frozenset[int] — service IDs для cross-validation
  (например handle_show_slots проверяет что service_id связан с master_id)
- summary_text: str — рендер для system_prompt'а с явными ID

system_prompt должен ВСЕГДА содержать список реальных ID — иначе LLM
галлюцинирует.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Prefetch

from services_app.models import Master, Service


DEFAULT_LIMIT = 20


@dataclass(frozen=True)
class MasterCandidate:
    """Один мастер для контекста LLM."""

    id: int
    name: str
    specialization: str
    services: list[tuple[int, str]]  # (service_id, name) для cross-validation


@dataclass(frozen=True)
class MasterContext:
    """Bundle мастеров + service IDs + summary для system_prompt'а."""

    candidates: list[MasterCandidate]
    candidate_ids: frozenset[int]
    candidate_service_ids: frozenset[int]
    summary_text: str


def build_master_context(*, limit: int = DEFAULT_LIMIT) -> MasterContext:
    """Top-N активных мастеров с их услугами.

    Дешёвый вызов — single ORM-query + prefetch. Безопасно вызывать на каждом
    chat-turn'е. Если подключённые услуги > 5, в summary показываем top-5
    (по имени), но в candidate_service_ids — все.
    """
    qs = (
        Master.objects.filter(is_active=True)
        .prefetch_related(
            Prefetch(
                "services",
                queryset=Service.objects.filter(is_active=True).order_by("name"),
            )
        )
        .order_by("order", "name")[:limit]
    )

    candidates: list[MasterCandidate] = []
    all_service_ids: set[int] = set()

    for master in qs:
        services = list(master.services.all())
        all_service_ids.update(s.id for s in services)
        candidates.append(MasterCandidate(
            id=master.id,
            name=master.name,
            specialization=(master.specialization or "").strip(),
            services=[(s.id, s.name) for s in services],
        ))

    return MasterContext(
        candidates=candidates,
        candidate_ids=frozenset(c.id for c in candidates),
        candidate_service_ids=frozenset(all_service_ids),
        summary_text=_render_summary(candidates),
    )


def _render_summary(candidates: list[MasterCandidate]) -> str:
    """Компактный markdown-список мастеров для system_prompt'а.

    Цель: < 500 токенов даже для 20 мастеров. Формат:
        - id=42 Анна Иванова (массаж классический): массаж спины, лимфодренаж, ...
    LLM получает список доступных int IDs, на которые он может ссылаться
    в tool-call'ах.
    """
    if not candidates:
        return "(нет активных мастеров — записаться можно только через менеджера)"

    lines: list[str] = []
    for c in candidates:
        spec = f" ({c.specialization})" if c.specialization else ""
        # Топ-5 услуг для prompt'а — больше всего раздуёт context
        top_services = c.services[:5]
        services_text = ", ".join(name for _, name in top_services)
        services_part = f": {services_text}" if services_text else ""
        if len(c.services) > 5:
            services_part += f" +ещё {len(c.services) - 5}"
        lines.append(f"- id={c.id} {c.name}{spec}{services_part}")
    return "\n".join(lines)
