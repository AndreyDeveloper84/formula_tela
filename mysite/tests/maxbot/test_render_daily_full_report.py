"""Phase 3.1 Part 2C T01: hybrid daily report render."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_render_daily_full_report_includes_meals_water_macros():
    """Базовый формат (Design §6.2): emoji приёмов + ккал + БЖУ + вода."""
    from maxbot.ai_ui import render_daily_full_report

    summary = MagicMock(
        date="30 апреля",
        calories_total=1380, calories_goal=1450,
        protein_g=98, fat_g=52, carbs_g=145,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша с ягодами", "calories": 320},
            {"meal_type": "lunch", "dish_name": "борщ + гречка", "calories": 520},
            {"meal_type": "dinner", "dish_name": "рыба + овощи", "calories": 380},
            {"meal_type": "snack", "dish_name": "яблоко + орехи", "calories": 160},
        ],
    )
    water_today = MagicMock(total_ml=1800, norm_ml=2000)

    text = render_daily_full_report(summary, water_today)

    # Header
    assert "30 апреля" in text or "Итоги" in text or "🌙" in text
    # Calories progress
    assert "1380" in text
    assert "1450" in text
    # Macros
    assert "98" in text and "52" in text and "145" in text
    # Water
    assert "1.8" in text or "1800" in text
    assert "2.0" in text or "2000" in text
    # Meals — emoji per time-of-day (per Design §6.2: 🌅 ☀️ 🌙 🍎)
    assert "каша с ягодами" in text
    assert "борщ" in text
    assert "рыба" in text
    assert "320" in text  # breakfast kcal


def test_render_daily_full_report_without_water_omits_water_section():
    """water_today=None → water раздел просто отсутствует (не падает)."""
    from maxbot.ai_ui import render_daily_full_report

    summary = MagicMock(
        date="2026-05-04",
        calories_total=800, calories_goal=1450,
        protein_g=40, fat_g=20, carbs_g=80,
        entries=[
            {"meal_type": "breakfast", "dish_name": "омлет", "calories": 400},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 400},
        ],
    )

    text = render_daily_full_report(summary, water_today=None)
    # Не должно быть "💧" или "л воды"
    assert "💧" not in text
    assert "омлет" in text


def test_render_thin_day_with_one_entry_says_only():
    """≤2 entries → §6.4 supportive template."""
    from maxbot.ai_ui import render_daily_full_report

    summary = MagicMock(
        date="2026-05-04",
        calories_total=320, calories_goal=1450,
        protein_g=12, fat_g=8, carbs_g=40,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
        ],
    )
    text = render_daily_full_report(summary, water_today=None)

    # Supportive template
    assert "немного" in text.lower() or "не" in text.lower()
    assert "каша" in text
    # Спрашивает «как самочувствие»
    assert "самочувств" in text.lower() or "пропустила" in text.lower()


def test_render_thin_day_under_50_percent_calories():
    """3+ entries но <50% от goal → thin-day template."""
    from maxbot.ai_ui import render_daily_full_report

    summary = MagicMock(
        date="2026-05-04",
        calories_total=600, calories_goal=1500,  # 40% — under 50
        protein_g=30, fat_g=20, carbs_g=60,
        entries=[
            {"meal_type": "breakfast", "dish_name": "тост", "calories": 200},
            {"meal_type": "lunch", "dish_name": "салат", "calories": 250},
            {"meal_type": "snack", "dish_name": "яблоко", "calories": 150},
        ],
    )
    text = render_daily_full_report(summary, water_today=None)

    assert "немного" in text.lower() or "пропустила" in text.lower()


def test_render_eating_disorder_mode_no_calories():
    """eating_disorder=True → нет цифр калорий, supportive «как ты сегодня?»."""
    from maxbot.ai_ui import render_daily_full_report

    summary = MagicMock(
        date="2026-05-04",
        calories_total=1300, calories_goal=1450,
        protein_g=80, fat_g=40, carbs_g=130,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 380},
            {"meal_type": "snack", "dish_name": "орехи", "calories": 150},
        ],
    )
    water_today = MagicMock(total_ml=1800, norm_ml=2000)

    text = render_daily_full_report(
        summary, water_today, eating_disorder=True,
    )

    # No calorie numbers
    assert "1300" not in text
    assert "1450" not in text
    assert "ккал" not in text
    # Supportive vibe
    assert "Как ты сегодня" in text or "День получился" in text
    # Meal mentions без чисел
    assert "завтрак" in text.lower() or "обед" in text.lower()
