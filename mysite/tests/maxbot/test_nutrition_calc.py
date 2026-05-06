"""Pure-math утилиты для anketa (Phase 3.1 Part 1 T01).

BMR / норма ккал считаются на Ayla side — здесь только локальные
вспомогательные функции (BMI для ladder-кнопок до отправки в Ayla).
"""
from __future__ import annotations

import pytest


def test_calc_bmi_normal_woman():
    """Стандартный случай — норма BMI = 22.0 для 60кг/165см."""
    from maxbot.nutrition_calc import calc_bmi

    bmi = calc_bmi(weight_kg=60, height_cm=165)
    assert 21.9 < bmi < 22.1


def test_calc_bmi_under_18_5_threshold():
    """BMI 18.4 (граница underweight) — для триггера ladder."""
    from maxbot.nutrition_calc import calc_bmi

    bmi = calc_bmi(weight_kg=50, height_cm=165)
    assert bmi < 18.5


def test_calc_bmi_zero_height_raises():
    """Гарда от деления на ноль — height=0 не должен крашить весь handler."""
    from maxbot.nutrition_calc import calc_bmi

    with pytest.raises(ValueError, match="height_cm must be positive"):
        calc_bmi(weight_kg=60, height_cm=0)


def test_calc_bmi_returns_float():
    """Тип результата — float (нам нужно сравнивать с 18.5)."""
    from maxbot.nutrition_calc import calc_bmi

    assert isinstance(calc_bmi(weight_kg=70, height_cm=170), float)
