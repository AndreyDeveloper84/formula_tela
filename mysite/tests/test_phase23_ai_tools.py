"""T02: ai_tools.py — OpenAI tool schemas + ActionType."""
from __future__ import annotations

import pytest


# ─── ActionType — стабильный wire-format ──────────────────────────────────


def test_action_type_constants():
    from maxbot.ai_tools import ActionType
    assert ActionType.SHOW_MASTERS == "show_masters"
    assert ActionType.SHOW_SLOTS == "show_slots"
    assert ActionType.CONFIRM_BOOKING == "confirm_booking"
    assert ActionType.SHOW_MY_BOOKINGS == "show_my_bookings"
    assert ActionType.ASK_CLARIFICATION == "ask_clarification"


def test_action_type_all_mvp_complete():
    from maxbot.ai_tools import ActionType
    assert ActionType.ALL_MVP == frozenset({
        "show_masters", "show_slots", "confirm_booking",
        "show_my_bookings", "recommend_services", "ask_clarification",
    })


# ─── TOOL_DEFINITIONS список ──────────────────────────────────────────────


def test_tool_definitions_has_6_tools():
    """Phase 2.4 T02: добавлен recommend_services."""
    from maxbot.ai_tools import TOOL_DEFINITIONS
    assert len(TOOL_DEFINITIONS) == 6


def test_tool_definitions_names_match_action_types():
    from maxbot.ai_tools import TOOL_DEFINITIONS, ActionType
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert names == ActionType.ALL_MVP


def test_each_tool_has_openai_shape():
    """Каждый tool — type=function + function.name + description + parameters."""
    from maxbot.ai_tools import TOOL_DEFINITIONS
    for tool in TOOL_DEFINITIONS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert "name" in fn and isinstance(fn["name"], str)
        assert "description" in fn and isinstance(fn["description"], str)
        assert "parameters" in fn
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params


# ─── show_masters — конкретные поля ───────────────────────────────────────


def test_show_masters_has_master_ids_and_explanation_required():
    from maxbot.ai_tools import SHOW_MASTERS
    params = SHOW_MASTERS["function"]["parameters"]
    assert "master_ids" in params["properties"]
    assert params["properties"]["master_ids"]["type"] == "array"
    # int IDs (наши Master.id), не UUID как в Ayla
    assert params["properties"]["master_ids"]["items"]["type"] == "integer"
    assert "explanation" in params["properties"]
    assert set(params["required"]) == {"master_ids", "explanation"}


def test_show_masters_optional_match_fields():
    from maxbot.ai_tools import SHOW_MASTERS
    props = SHOW_MASTERS["function"]["parameters"]["properties"]
    assert "match_scores" in props
    assert "match_reasons" in props


# ─── show_slots ────────────────────────────────────────────────────────────


def test_show_slots_required_master_service_date():
    from maxbot.ai_tools import SHOW_SLOTS
    params = SHOW_SLOTS["function"]["parameters"]
    props = params["properties"]
    assert props["master_id"]["type"] == "integer"
    assert props["service_id"]["type"] == "integer"
    assert props["date"]["type"] == "string"
    assert props["date"]["format"] == "date"
    assert set(params["required"]) == {"master_id", "service_id", "date"}


# ─── confirm_booking ──────────────────────────────────────────────────────


def test_confirm_booking_required_fields():
    from maxbot.ai_tools import CONFIRM_BOOKING
    params = CONFIRM_BOOKING["function"]["parameters"]
    props = params["properties"]
    assert props["master_id"]["type"] == "integer"
    assert props["service_id"]["type"] == "integer"
    assert props["datetime"]["type"] == "string"
    assert props["datetime"]["format"] == "date-time"
    assert set(params["required"]) == {"master_id", "service_id", "datetime"}


def test_confirm_booking_description_warns_against_creating_record():
    """Critical safety: tool description должна явно сказать что НЕ создаёт запись."""
    from maxbot.ai_tools import CONFIRM_BOOKING
    desc = CONFIRM_BOOKING["function"]["description"].lower()
    assert "not create" in desc or "не создаёт" in desc or "не создаст" in desc


# ─── show_my_bookings ─────────────────────────────────────────────────────


def test_show_my_bookings_filter_enum():
    from maxbot.ai_tools import SHOW_MY_BOOKINGS
    props = SHOW_MY_BOOKINGS["function"]["parameters"]["properties"]
    assert props["filter"]["enum"] == ["upcoming", "past", "all"]


# ─── ask_clarification ─────────────────────────────────────────────────────


def test_ask_clarification_question_required():
    from maxbot.ai_tools import ASK_CLARIFICATION
    params = ASK_CLARIFICATION["function"]["parameters"]
    assert "question" in params["properties"]
    assert "options" in params["properties"]
    assert params["required"] == ["question"]
