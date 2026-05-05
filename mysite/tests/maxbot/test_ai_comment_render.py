# mysite/tests/maxbot/test_ai_comment_render.py
"""Part 2D.3 T02: render_daily_full_report renders summary.ai_comment."""
from __future__ import annotations

from maxbot.services.nutrition_client import SummaryResponse, WaterTodayResponse


def _make_summary(*, ai_comment: str | None = None) -> SummaryResponse:
    return SummaryResponse(
        date="2026-05-05",
        calories_total=1100,
        calories_goal=1450,
        protein_g=65,
        fat_g=40,
        carbs_g=110,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 330},
        ],
        raw={},
        ai_comment=ai_comment,
    )


def test_render_includes_ai_comment_when_present():
    from maxbot.ai_ui import render_daily_full_report
    summary = _make_summary(ai_comment="Отличный день! Белка достаточно — продолжай.")
    text = render_daily_full_report(summary)
    assert "Отличный день!" in text


def test_render_omits_ai_comment_when_none():
    from maxbot.ai_ui import render_daily_full_report
    summary = _make_summary(ai_comment=None)
    text = render_daily_full_report(summary)
    # No empty trailing line, no «—» placeholder
    assert "💬" not in text  # icon used for ai_comment line — should be absent


def test_render_truncates_long_ai_comment_to_220_chars():
    from maxbot.ai_ui import render_daily_full_report
    long_comment = "А" * 500  # 500 chars
    summary = _make_summary(ai_comment=long_comment)
    text = render_daily_full_report(summary)
    # The rendered comment line should never exceed 220 chars (excluding emoji prefix)
    # Find the line starting with «💬 »
    comment_line = next((ln for ln in text.split("\n") if ln.startswith("💬 ")), None)
    assert comment_line is not None
    body = comment_line[2:].strip()  # strip "💬 " prefix
    assert len(body) <= 220


def test_render_strips_whitespace_in_ai_comment():
    """Defensive: AI may emit trailing newlines."""
    from maxbot.ai_ui import render_daily_full_report
    summary = _make_summary(ai_comment="  Хороший баланс.  \n\n")
    text = render_daily_full_report(summary)
    assert "💬 Хороший баланс." in text
    # No double newlines in comment block
    assert "\n\n💬" not in text or text.count("\n\n💬") <= 1


def test_render_eating_disorder_mode_skips_ai_comment():
    """Supportive template (§6.3) НЕ должен включать AI-comment с числами/советами."""
    from maxbot.ai_ui import render_daily_full_report
    summary = _make_summary(ai_comment="Ты съел 1100 из 1450 — добавь белка.")
    text = render_daily_full_report(summary, eating_disorder=True)
    # Eating-disorder mode hides numbers AND skips ai_comment content
    assert "1100" not in text
    assert "1450" not in text
    assert "добавь белка" not in text
    # Supportive chat-bubble template (§6.3) intact
    assert "Как ты сегодня" in text
