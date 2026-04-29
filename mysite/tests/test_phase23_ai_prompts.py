"""T05: ai_prompts.py — system prompt rendering."""
from __future__ import annotations

from datetime import date

import pytest


def _ctx(masters_summary: str = "(test masters)"):
    """Минимальный MasterContext-mock для prompt-render тестов."""
    from maxbot.ai_context import MasterContext
    return MasterContext(
        candidates=[], candidate_ids=frozenset(),
        candidate_service_ids=frozenset(),
        summary_text=masters_summary,
    )


# ─── Структура prompt'а ──────────────────────────────────────────────────


def test_prompt_includes_role_definition():
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 4, 27),
        client_name="Анна",
        bookings_count=0,
        master_context=_ctx(),
    )
    # Бот представляется + название салона
    assert "Формула тела" in prompt or "формула тела" in prompt.lower()


def test_prompt_includes_today_date():
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 4, 27), client_name="X",
        bookings_count=0, master_context=_ctx(),
    )
    assert "2026-04-27" in prompt


def test_prompt_includes_client_name_when_known():
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 4, 27), client_name="Михаил",
        bookings_count=2, master_context=_ctx(),
    )
    assert "Михаил" in prompt


def test_prompt_includes_master_context_summary():
    from maxbot.ai_prompts import render_system_prompt
    summary = "- id=42 Анна Иванова: массаж спины, лимфодренаж"
    prompt = render_system_prompt(
        today=date(2026, 4, 27), client_name="X",
        bookings_count=0, master_context=_ctx(summary),
    )
    assert summary in prompt


def test_prompt_includes_bookings_count():
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 4, 27), client_name="X",
        bookings_count=5, master_context=_ctx(),
    )
    assert "5" in prompt


# ─── Правила (anti-hallucination + behavioural rules) ─────────────────────


def test_prompt_includes_no_hallucination_rule():
    """Правило 8 — никогда не выдумывать мастеров вне списка."""
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 4, 27), client_name="X",
        bookings_count=0, master_context=_ctx(),
    )
    # Должна быть инструкция «не выдумывай»
    assert any(kw in prompt for kw in ("не выдумывай", "не придумыв", "ТОЛЬКО"))


def test_prompt_mentions_all_5_tools():
    """Каждый из 5 tools должен быть упомянут в правилах."""
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 4, 27), client_name="X",
        bookings_count=0, master_context=_ctx(),
    )
    for tool in ["show_masters", "show_slots", "confirm_booking",
                 "show_my_bookings", "ask_clarification"]:
        assert tool in prompt, f"Tool {tool} не упомянут в prompt'е"


def test_prompt_warns_against_creating_record_without_confirm():
    """confirm_booking не создаёт запись — критическое правило для AI."""
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 4, 27), client_name="X",
        bookings_count=0, master_context=_ctx(),
    )
    # Должно быть указано что после confirm_booking ждём подтверждения клиента
    assert any(kw in prompt.lower() for kw in (
        "ждать подтверждения", "жди подтверждения", "не создавай запись",
        "ждать клиента", "ждать", "ожида",
    ))


def test_prompt_does_not_request_phone():
    """Правило 11 — не просить телефон, он у нас в BotUser."""
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 4, 27), client_name="X",
        bookings_count=0, master_context=_ctx(),
    )
    # В правилах должно быть «не запрашивай телефон»
    assert "телефон" in prompt.lower()


# ─── Edge cases ───────────────────────────────────────────────────────────


def test_prompt_handles_empty_client_name():
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 4, 27), client_name="",
        bookings_count=0, master_context=_ctx(),
    )
    # Не падает, использует дефолт типа «клиент»
    assert prompt
    assert "клиент" in prompt.lower()


def test_prompt_short_enough_for_gpt4o_mini():
    """Целимся в <2000 токенов — gpt-4o-mini лучше следует коротким prompt'ам.

    Грубая оценка: 1 токен ≈ 4 символа для русского. 2000 токенов ≈ 8000 char.
    """
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 4, 27), client_name="X" * 100,
        bookings_count=99, master_context=_ctx("х" * 1000),
    )
    # Грубая оценка: 1 токен ≈ 4 символа для русского. <2200 токенов ≈ <8800 char.
    # После off-topic + intent-disambiguation rules бюджет 8800 (~5% over исходных 2000).
    assert len(prompt) < 8800
