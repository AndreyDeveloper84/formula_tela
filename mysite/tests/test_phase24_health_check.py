"""Phase 2.4 T03 — health screening для опасных услуг.

Логика prompt-only: маркер ⚠health в context + правило в system_prompt.
Тесты проверяют что:
- DB-поля requires_health_check + contraindications работают
- _render_summary отмечает опасные услуги
- recommend_services передаёт requires_health_check в action_data
- render_recommend_services показывает ⚠️ в карточке
"""
from __future__ import annotations

import pytest
from model_bakery import baker

from services_app.models import Service


# ─── Model defaults ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_service_health_check_defaults():
    s = baker.make(Service, is_active=True)
    assert s.requires_health_check is False
    assert s.contraindications == ""


@pytest.mark.django_db
def test_service_with_health_check_fields():
    s = baker.make(
        Service, is_active=True,
        requires_health_check=True,
        contraindications="Беременность, гипертония, онкология.",
    )
    s.refresh_from_db()
    assert s.requires_health_check is True
    assert "беременность" in s.contraindications.lower()


# ─── _render_summary marker ───────────────────────────────────────────────


@pytest.mark.django_db
def test_render_summary_marks_health_check_services():
    """Услуги с requires_health_check=True маркируются ⚠health в context."""
    from maxbot.ai_context import build_master_context
    from services_app.models import Master

    safe_svc = baker.make(
        Service, name="Классический массаж", is_active=True,
        requires_health_check=False,
    )
    danger_svc = baker.make(
        Service, name="Антицеллюлитный", is_active=True,
        requires_health_check=True,
    )
    master = baker.make(Master, is_active=True)
    master.services.set([safe_svc, danger_svc])

    ctx = build_master_context()
    summary = ctx.summary_text

    # ⚠health стоит у danger_svc
    assert f"service_id={danger_svc.id} {danger_svc.name} ⚠health" in summary
    # У safe_svc — нет маркера
    safe_line = f"service_id={safe_svc.id} {safe_svc.name}"
    # Должна быть строка которая содержит safe_line И НЕ заканчивается ⚠health
    found = False
    for line in summary.split("\n"):
        if safe_line in line:
            assert "⚠health" not in line.split(safe_svc.name)[1].split(";")[0]
            found = True
            break
    assert found


# ─── handle_recommend_services включает requires_health_check ─────────────


@pytest.mark.django_db
def test_recommend_services_passes_health_check_flag():
    from maxbot.ai_tool_handlers import handle_recommend_services

    baker.make(
        Service, name="Антицеллюлитный", is_active=True,
        goals=["cellulite"],
        requires_health_check=True,
        contraindications="Беременность, варикоз.",
    )
    result = handle_recommend_services({
        "goals": ["cellulite"], "explanation": "test",
    })
    services = result.action_data["services"]
    assert len(services) == 1
    assert services[0]["requires_health_check"] is True
    assert "беременность" in services[0]["contraindications"].lower()


@pytest.mark.django_db
def test_recommend_services_safe_service_no_health_flag():
    from maxbot.ai_tool_handlers import handle_recommend_services

    baker.make(
        Service, name="Релакс", is_active=True,
        goals=["relax"],
        requires_health_check=False,
    )
    result = handle_recommend_services({
        "goals": ["relax"], "explanation": "test",
    })
    services = result.action_data["services"]
    assert services[0]["requires_health_check"] is False
    assert services[0]["contraindications"] == ""


# ─── render shows warning ⚠️ ──────────────────────────────────────────────


def test_render_recommend_services_shows_health_warning():
    from maxbot.ai_ui import render_recommend_services

    text, _ = render_recommend_services(
        "conv-1",
        {
            "explanation": "Подобрала:",
            "services": [
                {"id": 1, "name": "Опасная", "duration_min": 60,
                 "price_from": "3000.00", "category": "Аппаратные",
                 "requires_health_check": True},
                {"id": 2, "name": "Безопасная", "duration_min": 60,
                 "price_from": "2000.00", "category": "Массажи",
                 "requires_health_check": False},
            ],
        },
    )
    assert "Опасная" in text
    assert "⚠️" in text
    # ⚠️ только у Опасной — Безопасная не должна иметь warning после своего name
    safe_idx = text.index("Безопасная")
    after_safe = text[safe_idx:safe_idx + 80]
    assert "⚠️" not in after_safe.split("\n")[0]


# ─── prompt rules ─────────────────────────────────────────────────────────


def test_prompt_includes_health_screening_rule():
    """system_prompt содержит правило про health-screening для ⚠health услуг."""
    from datetime import date
    from maxbot.ai_context import MasterContext
    from maxbot.ai_prompts import render_system_prompt

    ctx = MasterContext(
        candidates=[], candidate_ids=frozenset(),
        candidate_service_ids=frozenset(), summary_text="(тест)",
    )
    prompt = render_system_prompt(
        today=date(2026, 4, 29), client_name="Тест",
        bookings_count=0, master_context=ctx,
    )
    assert "⚠health" in prompt
    assert "беременности" in prompt.lower()
    assert "противопоказан" in prompt.lower() or "health" in prompt.lower()
