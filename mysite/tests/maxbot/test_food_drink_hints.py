"""DRF-358 T01: food/drink hints detector — used когда parse_beverage miss
но текст похож на еду/напиток (для friendly clarification card)."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("text", [
    "Борщ 300грамм",        # из реального диалога
    "Сок 0,5л",              # из реального диалога (с запятой)
    "Я выпил сок 0.5 л",    # из реального диалога (с точкой)
    "котлета",               # food word alone
    "паста с курицей",       # food word + words
    "стакан кваса",          # drink word (квас не в parse_beverage)
    "пицца 200г",            # food + grams pattern
    "морс 250 мл",           # drink + ml pattern
    "5 пельменей",           # number first + food
    "омлет 2 яйца",          # food + count
    "куриный суп",           # food
    "кефир",                 # drink word standalone
])
def test_looks_like_food_drink_positive(text):
    from maxbot.food_drink_hints import looks_like_food_drink
    assert looks_like_food_drink(text) is True


@pytest.mark.parametrize("text", [
    "Привет",                # phatic
    "Шея болит",             # pain
    "Как записаться?",       # booking
    "Сколько стоит массаж?", # service question
    "Спасибо",               # phatic
    "В каком районе салон",  # FAQ
    "",                      # empty
    "    ",                  # whitespace
    "Я ходил вчера на массаж он мне очень помог отличная атмосфера и приятный мастер",  # >30 chars + no food word
])
def test_looks_like_food_drink_negative(text):
    from maxbot.food_drink_hints import looks_like_food_drink
    assert looks_like_food_drink(text) is False


def test_looks_like_food_drink_handles_non_string():
    from maxbot.food_drink_hints import looks_like_food_drink
    assert looks_like_food_drink(None) is False  # type: ignore[arg-type]
    assert looks_like_food_drink(42) is False  # type: ignore[arg-type]


def test_looks_like_food_drink_case_insensitive():
    from maxbot.food_drink_hints import looks_like_food_drink
    assert looks_like_food_drink("БОРЩ 300Г") is True
    assert looks_like_food_drink("Котлета") is True


def test_looks_like_food_drink_long_text_with_food_word_still_false():
    """≤30 chars rule prevents false-positive on long pain consultations
    that happen to mention food."""
    from maxbot.food_drink_hints import looks_like_food_drink
    long_text = "После того как я съел вчера борщ у меня началась изжога что делать"
    # >30 chars → False даже если содержит «борщ»
    assert looks_like_food_drink(long_text) is False
