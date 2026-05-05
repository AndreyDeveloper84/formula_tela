"""Phase 3.2A T02: detect_health_signal regex helper."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("text,expected", [
    ("я беременная, что мне можно?", "pregnancy"),
    ("кормлю грудью малыша", "breastfeeding"),
    ("у меня диабет 2го типа", "diabetes"),
    ("давление 140/90", "hypertension"),
    ("у меня срыв был вчера, помоги", "eating_disorder"),
    ("ненавижу свой вес", "eating_disorder"),
    ("после выкидыша не могу набрать вес", "pregnancy"),
])
def test_detect_health_signal_positive(text, expected):
    from maxbot.tier_b_triggers import detect_health_signal
    assert detect_health_signal(text) == expected


@pytest.mark.parametrize("text", [
    "хочу записаться на массаж",
    "сколько калорий в гречке?",
    "что съесть на завтрак",
    "",
    "    ",
])
def test_detect_health_signal_negative(text):
    from maxbot.tier_b_triggers import detect_health_signal
    assert detect_health_signal(text) is None


def test_detect_health_signal_case_insensitive():
    from maxbot.tier_b_triggers import detect_health_signal
    assert detect_health_signal("БЕРЕМЕННАЯ") == "pregnancy"


def test_detect_health_signal_handles_non_string():
    from maxbot.tier_b_triggers import detect_health_signal
    assert detect_health_signal(None) is None  # type: ignore[arg-type]
