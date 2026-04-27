"""T04: ai_context.py — построение MasterContext для system_prompt'а."""
from __future__ import annotations

import pytest
from model_bakery import baker

pytestmark = pytest.mark.django_db


# ─── MasterCandidate dataclass ─────────────────────────────────────────────


def test_master_candidate_fields():
    from maxbot.ai_context import MasterCandidate
    c = MasterCandidate(
        id=1, name="Анна", specialization="массаж",
        services=[(10, "массаж спины"), (11, "лимфодренаж")],
    )
    assert c.id == 1
    assert c.name == "Анна"
    assert len(c.services) == 2


# ─── build_master_context ─────────────────────────────────────────────────


def test_build_master_context_returns_active_only():
    from maxbot.ai_context import build_master_context
    from services_app.models import Master, Service
    svc = baker.make(Service, name="Массаж")
    active = baker.make(Master, name="Активный", is_active=True)
    inactive = baker.make(Master, name="Неактивный", is_active=False)
    active.services.add(svc)
    inactive.services.add(svc)

    ctx = build_master_context()

    assert active.id in ctx.candidate_ids
    assert inactive.id not in ctx.candidate_ids


def test_build_master_context_includes_services():
    from maxbot.ai_context import build_master_context
    from services_app.models import Master, Service
    s1 = baker.make(Service, name="Массаж спины")
    s2 = baker.make(Service, name="Лимфодренаж")
    m = baker.make(Master, name="Анна", is_active=True)
    m.services.add(s1, s2)

    ctx = build_master_context()
    candidate = next(c for c in ctx.candidates if c.id == m.id)
    service_names = {svc[1] for svc in candidate.services}
    assert "Массаж спины" in service_names
    assert "Лимфодренаж" in service_names


def test_build_master_context_summary_text_lists_masters():
    from maxbot.ai_context import build_master_context
    from services_app.models import Master, Service
    svc = baker.make(Service, name="Массаж")
    m1 = baker.make(Master, name="Анна Иванова", is_active=True,
                    specialization="массаж классический")
    m2 = baker.make(Master, name="Денис Петров", is_active=True,
                    specialization="спортивный массаж")
    m1.services.add(svc); m2.services.add(svc)

    ctx = build_master_context()
    text = ctx.summary_text
    assert "Анна Иванова" in text
    assert "Денис Петров" in text
    # Содержит ID мастеров — критично для anti-hallucination в LLM prompt'е
    assert f"id={m1.id}" in text or f"#{m1.id}" in text


def test_build_master_context_candidate_service_ids_set():
    """candidate_service_ids — для cross-validation в handlers (handle_show_slots)."""
    from maxbot.ai_context import build_master_context
    from services_app.models import Master, Service
    s1 = baker.make(Service, name="Массаж")
    s2 = baker.make(Service, name="Лазер")
    m = baker.make(Master, is_active=True)
    m.services.add(s1, s2)

    ctx = build_master_context()
    assert s1.id in ctx.candidate_service_ids
    assert s2.id in ctx.candidate_service_ids


def test_build_master_context_empty_when_no_active_masters():
    """Edge case — нет активных мастеров."""
    from maxbot.ai_context import build_master_context
    from services_app.models import Master
    Master.objects.all().delete()
    ctx = build_master_context()
    assert ctx.candidates == []
    assert ctx.candidate_ids == frozenset()
    assert ctx.summary_text  # не пустая, но информативная заглушка


def test_build_master_context_respects_limit():
    """Top-N мастеров — не больше лимита."""
    from maxbot.ai_context import build_master_context
    from services_app.models import Master, Service
    svc = baker.make(Service)
    for i in range(25):
        m = baker.make(Master, is_active=True, order=i)
        m.services.add(svc)
    ctx = build_master_context(limit=10)
    assert len(ctx.candidates) == 10


def test_build_master_context_orders_by_order_then_name():
    """Сортировка для детерминированности (Master.Meta.ordering = ['order', 'name'])."""
    from maxbot.ai_context import build_master_context
    from services_app.models import Master, Service
    svc = baker.make(Service)
    m1 = baker.make(Master, name="Z последний", is_active=True, order=2)
    m2 = baker.make(Master, name="A первый", is_active=True, order=1)
    m1.services.add(svc); m2.services.add(svc)
    ctx = build_master_context()
    ids = [c.id for c in ctx.candidates]
    assert ids.index(m2.id) < ids.index(m1.id)
