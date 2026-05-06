"""Phase 3.1 Part 2B T09: render_water_added rendering coverage."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_render_water_added_with_alcohol_hint():
    """alcohol_recovery_hint=True → render appends water-recovery hint."""
    from maxbot.ai_ui import render_water_added

    entry = MagicMock(
        ml=200, today_total_ml=1500, today_norm_ml=2000,
        milestone_text=None, alcohol_recovery_hint=True,
    )

    text = render_water_added(entry)
    assert "🍷" in text or "Алкоголь" in text or "обезвожив" in text.lower()


def test_render_water_added_with_milestone():
    """milestone_text — рендерится отдельной строкой."""
    from maxbot.ai_ui import render_water_added

    entry = MagicMock(
        ml=500, today_total_ml=1000, today_norm_ml=2000,
        milestone_text="Половина нормы — отлично!",
        alcohol_recovery_hint=False,
    )

    text = render_water_added(entry)
    assert "Половина нормы" in text


def test_render_water_added_basic_format():
    """Нет milestone, нет alcohol — только base format."""
    from maxbot.ai_ui import render_water_added

    entry = MagicMock(
        ml=250, today_total_ml=1450, today_norm_ml=2000,
        milestone_text=None, alcohol_recovery_hint=False,
    )

    text = render_water_added(entry)
    assert "+250" in text
    assert "1.4" in text or "1450" in text
    assert "2.0" in text or "2000" in text
    # No extras
    assert "🍷" not in text
    assert "беремен" not in text.lower()
