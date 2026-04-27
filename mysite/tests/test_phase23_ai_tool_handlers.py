"""T03: ai_tool_handlers.py — валидаторы tool-args + anti-hallucination."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from model_bakery import baker

pytestmark = pytest.mark.django_db


def _ctx_with_masters(masters: list, services: list | None = None):
    """Test helper: MasterContext с указанными master/service IDs."""
    from maxbot.ai_context import MasterCandidate, MasterContext
    candidates = [
        MasterCandidate(
            id=m.id, name=m.name, specialization=m.specialization or "",
            services=[(s.id, s.name) for s in (services or [])],
        )
        for m in masters
    ]
    all_service_ids = frozenset(s.id for s in (services or []))
    return MasterContext(
        candidates=candidates,
        candidate_ids=frozenset(c.id for c in candidates),
        candidate_service_ids=all_service_ids,
        summary_text="(test)",
    )


# ─── _safe_int ────────────────────────────────────────────────────────────


def test_safe_int_accepts_real_int():
    from maxbot.ai_tool_handlers import _safe_int
    assert _safe_int(42) == 42


def test_safe_int_accepts_numeric_string():
    from maxbot.ai_tool_handlers import _safe_int
    assert _safe_int("42") == 42


def test_safe_int_rejects_garbage():
    from maxbot.ai_tool_handlers import _safe_int
    assert _safe_int("abc") is None
    assert _safe_int(None) is None
    assert _safe_int("") is None
    assert _safe_int([]) is None


# ─── _fallback_clarification ──────────────────────────────────────────────


def test_fallback_clarification_returns_ask_action():
    from maxbot.ai_tool_handlers import _fallback_clarification
    result = _fallback_clarification("test_reason")
    assert result.action_type == "ask_clarification"
    assert "question" in result.action_data
    assert "options" in result.action_data


# ─── handle_show_masters ──────────────────────────────────────────────────


def test_handle_show_masters_filters_invalid_ids():
    """LLM выдумал master_id 999 — фильтруем, оставляем только валидные."""
    from maxbot.ai_tool_handlers import handle_show_masters
    from services_app.models import Master
    real = baker.make(Master, name="Анна", is_active=True)
    ctx = _ctx_with_masters([real])

    args = {
        "master_ids": [real.id, 999, 888],  # один реальный, два галлюцинированных
        "explanation": "подходит для массажа",
    }
    result = handle_show_masters(args, ctx)
    assert result.action_type == "show_masters"
    masters = result.action_data["masters"]
    assert len(masters) == 1
    assert masters[0]["master"]["id"] == real.id


def test_handle_show_masters_all_invalid_falls_back():
    """LLM полностью галлюцинировал — fallback на ask_clarification."""
    from maxbot.ai_tool_handlers import handle_show_masters
    ctx = _ctx_with_masters([])
    args = {"master_ids": [999, 888], "explanation": "x"}
    result = handle_show_masters(args, ctx)
    assert result.action_type == "ask_clarification"


def test_handle_show_masters_includes_explanation_and_scores():
    from maxbot.ai_tool_handlers import handle_show_masters
    from services_app.models import Master
    m = baker.make(Master, name="Анна", is_active=True)
    ctx = _ctx_with_masters([m])
    args = {
        "master_ids": [m.id],
        "match_scores": [85],
        "match_reasons": [["опытная", "хорошие отзывы"]],
        "explanation": "подходит лучше всего",
    }
    result = handle_show_masters(args, ctx)
    assert result.action_data["explanation"] == "подходит лучше всего"
    assert result.action_data["masters"][0]["match_score"] == 85
    assert "опытная" in result.action_data["masters"][0]["match_reasons"]


# ─── handle_show_slots ────────────────────────────────────────────────────


def test_handle_show_slots_validates_master_in_context():
    """master_id вне context → fallback."""
    from maxbot.ai_tool_handlers import handle_show_slots
    ctx = _ctx_with_masters([])
    args = {"master_id": 999, "service_id": 1, "date": "2026-04-30"}
    result = handle_show_slots(args, ctx)
    assert result.action_type == "ask_clarification"


def test_handle_show_slots_validates_service_id_in_context():
    """service_id вне context → fallback."""
    from maxbot.ai_tool_handlers import handle_show_slots
    from services_app.models import Master, Service
    m = baker.make(Master, is_active=True)
    s = baker.make(Service)
    ctx = _ctx_with_masters([m], services=[s])
    args = {"master_id": m.id, "service_id": 9999, "date": "2026-04-30"}
    result = handle_show_slots(args, ctx)
    assert result.action_type == "ask_clarification"


def test_handle_show_slots_invalid_date_falls_back():
    from maxbot.ai_tool_handlers import handle_show_slots
    from services_app.models import Master, Service
    m = baker.make(Master, is_active=True)
    s = baker.make(Service)
    ctx = _ctx_with_masters([m], services=[s])
    args = {"master_id": m.id, "service_id": s.id, "date": "not-a-date"}
    result = handle_show_slots(args, ctx)
    assert result.action_type == "ask_clarification"


def test_handle_show_slots_returns_validated_payload():
    """Все args валидны → action_data с master_id, service_id, date.

    Реальный fetch слотов из YClients — в render layer (T07), не здесь.
    """
    from maxbot.ai_tool_handlers import handle_show_slots
    from services_app.models import Master, Service
    m = baker.make(Master, is_active=True)
    s = baker.make(Service, name="Массаж спины")
    ctx = _ctx_with_masters([m], services=[s])
    args = {"master_id": m.id, "service_id": s.id, "date": "2026-04-30"}
    result = handle_show_slots(args, ctx)
    assert result.action_type == "show_slots"
    assert result.action_data["master_id"] == m.id
    assert result.action_data["service_id"] == s.id
    assert result.action_data["date"] == "2026-04-30"


# ─── handle_confirm_booking ───────────────────────────────────────────────


def test_handle_confirm_booking_validates_ids_in_context():
    from maxbot.ai_tool_handlers import handle_confirm_booking
    ctx = _ctx_with_masters([])
    args = {"master_id": 999, "service_id": 1, "datetime": "2026-04-30T14:00:00+03:00"}
    result = handle_confirm_booking(args, ctx)
    assert result.action_type == "ask_clarification"


def test_handle_confirm_booking_invalid_datetime_falls_back():
    from maxbot.ai_tool_handlers import handle_confirm_booking
    from services_app.models import Master, Service
    m = baker.make(Master, is_active=True)
    s = baker.make(Service)
    ctx = _ctx_with_masters([m], services=[s])
    args = {"master_id": m.id, "service_id": s.id, "datetime": "not-iso"}
    result = handle_confirm_booking(args, ctx)
    assert result.action_type == "ask_clarification"


def test_handle_confirm_booking_returns_validated_payload():
    from maxbot.ai_tool_handlers import handle_confirm_booking
    from services_app.models import Master, Service
    m = baker.make(Master, is_active=True)
    s = baker.make(Service, name="Массаж спины")
    ctx = _ctx_with_masters([m], services=[s])
    args = {
        "master_id": m.id, "service_id": s.id,
        "datetime": "2026-04-30T14:00:00+03:00",
    }
    result = handle_confirm_booking(args, ctx)
    assert result.action_type == "confirm_booking"
    assert result.action_data["master_id"] == m.id
    assert result.action_data["service_id"] == s.id
    assert result.action_data["datetime"] == "2026-04-30T14:00:00+03:00"
    # Также для UI рендеринга — имена
    assert result.action_data["master_name"] == m.name
    assert result.action_data["service_name"] == s.name


# ─── handle_show_my_bookings ──────────────────────────────────────────────


def test_handle_show_my_bookings_default_filter_upcoming():
    from maxbot.ai_tool_handlers import handle_show_my_bookings
    args = {}
    result = handle_show_my_bookings(args)
    assert result.action_type == "show_my_bookings"
    assert result.action_data["filter"] == "upcoming"


def test_handle_show_my_bookings_validates_filter_enum():
    from maxbot.ai_tool_handlers import handle_show_my_bookings
    args = {"filter": "garbage"}
    result = handle_show_my_bookings(args)
    # Garbage filter → дефолт upcoming, не fallback
    assert result.action_type == "show_my_bookings"
    assert result.action_data["filter"] == "upcoming"


def test_handle_show_my_bookings_accepts_valid_filter():
    from maxbot.ai_tool_handlers import handle_show_my_bookings
    for f in ["upcoming", "past", "all"]:
        args = {"filter": f}
        result = handle_show_my_bookings(args)
        assert result.action_data["filter"] == f


# ─── handle_ask_clarification ─────────────────────────────────────────────


def test_handle_ask_clarification_passes_through():
    from maxbot.ai_tool_handlers import handle_ask_clarification
    args = {"question": "В какой день?", "options": ["Завтра", "Понедельник"]}
    result = handle_ask_clarification(args)
    assert result.action_type == "ask_clarification"
    assert result.action_data["question"] == "В какой день?"
    assert result.action_data["options"] == ["Завтра", "Понедельник"]


def test_handle_ask_clarification_empty_question_falls_back():
    """LLM эмиттит пустой question — fallback с дефолтом."""
    from maxbot.ai_tool_handlers import handle_ask_clarification
    result = handle_ask_clarification({})
    assert result.action_type == "ask_clarification"
    assert result.action_data["question"]  # не пустой


# ─── dispatch_tool_call ───────────────────────────────────────────────────


def _mock_tool_call(name: str, arguments: dict):
    """Mock OpenAI tool_call object."""
    import json
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def test_dispatch_show_masters():
    from maxbot.ai_tool_handlers import dispatch_tool_call
    from services_app.models import Master
    m = baker.make(Master, is_active=True)
    ctx = _ctx_with_masters([m])
    tc = _mock_tool_call("show_masters", {"master_ids": [m.id], "explanation": "x"})
    result = dispatch_tool_call(tc, ctx)
    assert result.action_type == "show_masters"


def test_dispatch_unknown_tool_falls_back():
    from maxbot.ai_tool_handlers import dispatch_tool_call
    ctx = _ctx_with_masters([])
    tc = _mock_tool_call("unknown_tool", {})
    result = dispatch_tool_call(tc, ctx)
    assert result.action_type == "ask_clarification"


def test_dispatch_invalid_json_arguments_falls_back():
    """Если LLM вернул невалидный JSON в arguments — fallback."""
    from maxbot.ai_tool_handlers import dispatch_tool_call
    ctx = _ctx_with_masters([])
    tc = MagicMock()
    tc.function.name = "show_masters"
    tc.function.arguments = "{not valid json"
    result = dispatch_tool_call(tc, ctx)
    assert result.action_type == "ask_clarification"
