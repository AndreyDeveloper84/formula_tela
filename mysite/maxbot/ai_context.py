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
    """Компактный markdown-список мастеров + услуг с РЕАЛЬНЫМИ ID для system_prompt'а.

    Цель: <500 токенов даже для 20 мастеров. Формат:
        - master_id=42 Анна Иванова (массаж):
            * service_id=10 массаж спины
            * service_id=11 лимфодренаж
            * +ещё 11

    LLM получает явные `master_id=N` И `service_id=N` — без них он галлюцинирует
    идентификаторы (incident 2026-04-27: LLM передал service_id=1 которого нет
    в БД, handler сфолбекнулся на ask_clarification).

    Trade-off: длиннее на ~50 токенов на мастера vs anti-hallucination win.
    """
    if not candidates:
        return "(нет активных мастеров — записаться можно только через менеджера)"

    lines: list[str] = []
    for c in candidates:
        spec = f" ({c.specialization})" if c.specialization else ""
        lines.append(f"- master_id={c.id} {c.name}{spec}:")
        # Топ-5 услуг с явными service_id — LLM использует их в show_slots/confirm_booking
        top_services = c.services[:5]
        for sid, name in top_services:
            lines.append(f"    * service_id={sid} {name}")
        if len(c.services) > 5:
            lines.append(f"    * +ещё {len(c.services) - 5} услуг")
    return "\n".join(lines)
