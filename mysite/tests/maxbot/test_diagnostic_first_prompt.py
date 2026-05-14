# mysite/tests/maxbot/test_diagnostic_first_prompt.py
"""DRF-358 T04: verify diagnostic-first rule + red-flag list присутствуют
в rendered system prompt + voice examples list содержит pain-consultation
flow."""
from __future__ import annotations

from datetime import date

from maxbot.ai_context import MasterContext


def _make_ctx() -> MasterContext:
    return MasterContext(
        candidates=[],
        candidate_ids=frozenset(),
        candidate_service_ids=frozenset(),
        summary_text="(тест)",
    )


def test_diagnostic_first_rule_in_prompt():
    """System prompt содержит явное правило: при упоминании боли AI
    задаёт ≥1 вопрос ДО tool_call."""
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 5, 8), client_name="Аня", bookings_count=0,
        master_context=_make_ctx(), last_visits=[],
    )
    lower = prompt.lower()
    # Diagnostic-first principle присутствует
    assert "уточн" in lower or "diagnostic" in lower or "вопрос" in lower
    # Боль / жалоба mentioned
    assert "боль" in lower or "жалоб" in lower


def test_red_flags_in_prompt():
    """Red-flag list присутствует — AI должен знать когда отправлять
    к врачу вместо продажи массажа."""
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 5, 8), client_name="Аня", bookings_count=0,
        master_context=_make_ctx(), last_visits=[],
    )
    lower = prompt.lower()
    # Хотя бы 2 red-flag слова из списка
    red_flags = ["отдаёт", "отдаст", "онемен", "ночью", "травм", "температур"]
    matched = sum(1 for f in red_flags if f in lower)
    assert matched >= 2, f"expected ≥2 red-flag words in prompt, found {matched}"
    # Doctor referral mention
    assert "врач" in lower or "невролог" in lower or "медицин" in lower


def test_no_corporate_apology_phrases_encouraged():
    """Prompt должен явно discourage «к сожалению, не могу помочь»."""
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 5, 8), client_name="Аня", bookings_count=0,
        master_context=_make_ctx(), last_visits=[],
    )
    lower = prompt.lower()
    # Discourage phrase explicitly mentioned (как badge для AI «избегай»)
    assert "к сожалению" in lower or "извин" in lower or "избегай" in lower


def test_pain_examples_rendered_in_prompt():
    """T04 fix: DIAGNOSTIC_FIRST_PAIN_EXAMPLES должны actually render
    в prompt — иначе rule без few-shot reinforcement (dead code in prod)."""
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 5, 8), client_name="Аня", bookings_count=0,
        master_context=_make_ctx(), last_visits=[],
    )
    # First pain example user line должен быть в prompt
    assert "Шея болит" in prompt or "Спина устаёт" in prompt
    # Diagnostic-first assistant pattern (вопрос «где конкретно» / numbered list)
    assert "?" in prompt


def test_voice_examples_includes_diagnostic_first_pain():
    """voice_examples.EXAMPLES содержит ≥3 pain-consultation diagnostic-first
    examples."""
    from maxbot.voice_examples import EXAMPLES
    pain_examples = [
        ex for ex in EXAMPLES
        if any(
            kw in ex.user.lower()
            for kw in ["болит", "болят", "ноет", "тянет", "напряг"]
        )
    ]
    assert len(pain_examples) >= 3, (
        f"expected ≥3 diagnostic-first pain examples, found {len(pain_examples)}"
    )
    # Хотя бы один example содержит уточняющий вопрос (не сразу tool-call)
    has_question = any(
        "?" in ex.assistant for ex in pain_examples
    )
    assert has_question, "pain examples should ask diagnostic questions"
