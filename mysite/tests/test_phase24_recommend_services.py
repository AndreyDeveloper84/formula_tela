"""Phase 2.4 T02 — recommend_services tool + render + handler."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from model_bakery import baker

from maxbot.ai_tool_handlers import (
    ToolResult,
    dispatch_tool_call,
    handle_recommend_services,
)
from maxbot.ai_tools import RECOMMEND_SERVICES, ActionType, TOOL_DEFINITIONS
from maxbot.ai_ui import render_recommend_services
from services_app.models import Service


# ─── Tool schema ──────────────────────────────────────────────────────────


def test_recommend_services_in_tool_definitions():
    names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
    assert "recommend_services" in names


def test_recommend_services_tool_schema_has_required_fields():
    fn = RECOMMEND_SERVICES["function"]
    assert fn["name"] == "recommend_services"
    params = fn["parameters"]["properties"]
    assert "goals" in params
    assert "explanation" in params
    assert fn["parameters"]["required"] == ["goals", "explanation"]


# ─── handle_recommend_services ────────────────────────────────────────────


@pytest.mark.django_db
def test_handle_recommend_services_filters_by_goals():
    """Возвращает только услуги с подходящим goal."""
    s_relax = baker.make(Service, name="Релакс массаж", is_active=True, goals=["relax"])
    s_back = baker.make(Service, name="Спина", is_active=True, goals=["back_pain"])
    s_other = baker.make(Service, name="Без целей", is_active=True, goals=[])

    result = handle_recommend_services({
        "goals": ["relax"],
        "explanation": "test",
    })
    assert result.action_type == ActionType.RECOMMEND_SERVICES
    names = [s["name"] for s in result.action_data["services"]]
    assert "Релакс массаж" in names
    assert "Спина" not in names
    assert "Без целей" not in names


@pytest.mark.django_db
def test_handle_recommend_services_dedupes_invalid_goals():
    """Невалидные тэги игнорируются (LLM иногда галлюцинирует)."""
    baker.make(Service, name="Релакс", is_active=True, goals=["relax"])

    result = handle_recommend_services({
        "goals": ["relax", "fake_goal_999"],
        "explanation": "test",
    })
    assert result.action_type == ActionType.RECOMMEND_SERVICES
    assert result.action_data["goals"] == ["relax"]


@pytest.mark.django_db
def test_handle_recommend_services_all_invalid_goals_falls_back():
    """Все теги невалидные → fallback на ask_clarification."""
    result = handle_recommend_services({
        "goals": ["invented_1", "fake_2"],
        "explanation": "test",
    })
    assert result.action_type == ActionType.ASK_CLARIFICATION


@pytest.mark.django_db
def test_handle_recommend_services_no_match_falls_back():
    """Goals валидные но услуг с этим тегом нет → ask_clarification."""
    baker.make(Service, name="Релакс", is_active=True, goals=["relax"])
    result = handle_recommend_services({
        "goals": ["cellulite"],
        "explanation": "",
    })
    assert result.action_type == ActionType.ASK_CLARIFICATION


@pytest.mark.django_db
def test_handle_recommend_services_orders_popular_first():
    """is_popular=True ранжируется выше."""
    s_normal = baker.make(
        Service, name="Обычная", is_active=True,
        is_popular=False, goals=["relax"],
    )
    s_popular = baker.make(
        Service, name="Популярная", is_active=True,
        is_popular=True, goals=["relax"],
    )

    result = handle_recommend_services({
        "goals": ["relax"], "explanation": "",
    })
    names = [s["name"] for s in result.action_data["services"]]
    assert names[0] == "Популярная"


@pytest.mark.django_db
def test_handle_recommend_services_includes_metadata():
    """Каждая услуга содержит id, name, price_from, duration_min, category, slug."""
    from services_app.models import ServiceCategory
    cat = baker.make(ServiceCategory, name="Массажи")
    svc = baker.make(
        Service, name="Тест", is_active=True,
        goals=["relax"],
        price_from=2500, duration_min=60,
        short_description="короткое описание",
        category=cat,
    )
    result = handle_recommend_services({
        "goals": ["relax"], "explanation": "",
    })
    assert len(result.action_data["services"]) == 1
    s = result.action_data["services"][0]
    assert s["id"] == svc.id
    assert s["name"] == "Тест"
    assert s["price_from"] == "2500.00"
    assert s["duration_min"] == 60
    assert s["category"] == "Массажи"
    assert s["short_description"] == "короткое описание"
    assert "relax" in s["goals"]


# ─── dispatch ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_dispatch_recommend_services():
    """LLM tool_call.name='recommend_services' → handle_recommend_services."""
    baker.make(Service, name="Релакс", is_active=True, goals=["relax"])

    tool_call = MagicMock()
    tool_call.function.name = "recommend_services"
    tool_call.function.arguments = json.dumps({
        "goals": ["relax"], "explanation": "test",
    })
    from maxbot.ai_context import MasterContext

    ctx = MasterContext(
        candidates=[], candidate_ids=frozenset(),
        candidate_service_ids=frozenset(), summary_text="",
    )
    result = dispatch_tool_call(tool_call, ctx)
    assert result.action_type == ActionType.RECOMMEND_SERVICES


# ─── render_recommend_services ────────────────────────────────────────────


def test_render_recommend_services_with_services():
    """Рендерит текст + кнопки на каждую услугу."""
    text, attachments = render_recommend_services(
        "conv-1",
        {
            "explanation": "Подобрала вам:",
            "services": [
                {"id": 10, "name": "Релакс", "duration_min": 60,
                 "price_from": "2500.00", "category": "Массажи",
                 "short_description": "расслабит"},
                {"id": 11, "name": "Антистресс", "duration_min": 90,
                 "price_from": "3500.00", "category": "Массажи",
                 "short_description": ""},
            ],
        },
    )
    assert "Подобрала вам" in text
    assert "Релакс" in text
    assert "Антистресс" in text
    assert "60 мин" in text
    assert "2500" in text
    assert "[Массажи]" in text
    assert "_расслабит_" in text  # short_description italic
    assert len(attachments) == 1


def test_render_recommend_services_empty_services():
    """Если services=[] (что не должно случаться — но защита) — graceful text."""
    text, attachments = render_recommend_services("conv-1", {"services": []})
    assert "не нашлось" in text.lower()
    assert attachments == []


def test_render_recommend_services_no_explanation():
    text, attachments = render_recommend_services(
        "conv-1",
        {
            "services": [
                {"id": 10, "name": "Х", "duration_min": 60, "price_from": "2000.00"},
            ],
        },
    )
    assert "Х" in text
    assert len(attachments) == 1
