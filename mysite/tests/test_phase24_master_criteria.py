"""Phase 2.4 T06 — master criteria для LLM-side фильтрации."""
from __future__ import annotations

import pytest
from model_bakery import baker

from services_app.models import Master


@pytest.mark.django_db
def test_master_candidate_includes_experience_and_approach():
    """build_master_context передаёт experience+approach в кандидата."""
    from maxbot.ai_context import build_master_context

    baker.make(
        Master, name="Анна", is_active=True,
        experience="10 лет",
        approach="<p>Мягкий релаксационный подход, без боли.</p>",
    )
    ctx = build_master_context()
    candidates = [c for c in ctx.candidates if c.name == "Анна"]
    assert len(candidates) == 1
    c = candidates[0]
    assert c.experience == "10 лет"
    assert "Мягкий" in c.approach
    # HTML стрипнут
    assert "<p>" not in c.approach


@pytest.mark.django_db
def test_render_summary_includes_experience_and_approach():
    """_render_summary рендерит «опыт: ...» и «подход: ...» для каждого мастера."""
    from maxbot.ai_context import build_master_context

    baker.make(
        Master, name="Денис", is_active=True,
        experience="5 лет",
        approach="Глубокая проработка мышц, спортивный массаж.",
    )
    ctx = build_master_context()
    summary = ctx.summary_text
    assert "опыт: 5 лет" in summary
    assert "подход:" in summary
    assert "Глубокая" in summary


@pytest.mark.django_db
def test_render_summary_truncates_long_approach():
    """approach > APPROACH_PREVIEW_CHARS обрезается с многоточием."""
    from maxbot.ai_context import build_master_context, APPROACH_PREVIEW_CHARS

    long_text = "очень длинный подход " * 50  # ~1000 chars
    baker.make(
        Master, name="Мария", is_active=True,
        approach=long_text,
    )
    ctx = build_master_context()
    summary = ctx.summary_text
    # Найти строку с подходом Марии и проверить
    assert "…" in summary  # маркер обрезки
    # Полный текст не вошёл
    assert long_text.strip() not in summary


@pytest.mark.django_db
def test_render_summary_skips_empty_meta():
    """Если у мастера нет ни experience ни approach — строка с meta не вставляется."""
    from maxbot.ai_context import build_master_context

    baker.make(
        Master, name="Без_данных", is_active=True,
        experience="", approach="",
    )
    ctx = build_master_context()
    summary = ctx.summary_text
    # Должна быть строка с master_id, но БЕЗ «опыт:» / «подход:»
    lines = summary.split("\n")
    target_idx = None
    for i, line in enumerate(lines):
        if "Без_данных" in line:
            target_idx = i
            break
    assert target_idx is not None
    # Строка СРАЗУ после master-line не должна содержать «опыт:» / «подход:»
    next_line = lines[target_idx + 1] if target_idx + 1 < len(lines) else ""
    assert "опыт:" not in next_line
    assert "подход:" not in next_line


def test_strip_html_helper():
    from maxbot.ai_context import _strip_html
    assert _strip_html("<p>Hello</p>") == " Hello "
    assert _strip_html("plain text") == "plain text"
    assert _strip_html("<b>bold</b> <i>italic</i>") == " bold   italic "


def test_prompt_rule_11_master_criteria():
    """Prompt содержит правило про критерии выбора мастера."""
    from datetime import date
    from maxbot.ai_context import MasterContext
    from maxbot.ai_prompts import render_system_prompt

    ctx = MasterContext(
        candidates=[], candidate_ids=frozenset(),
        candidate_service_ids=frozenset(), summary_text="(тест)",
    )
    prompt = render_system_prompt(
        today=date(2026, 4, 29), client_name="X",
        bookings_count=0, master_context=ctx,
    )
    assert "опытный" in prompt.lower() or "опыт" in prompt.lower()
    assert "мягкий" in prompt.lower()
    assert "сильный" in prompt.lower() or "глубок" in prompt.lower()
