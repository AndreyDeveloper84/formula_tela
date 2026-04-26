"""Тесты intent-router'а: phatic phrases (приветствие/благодарность/small-talk)."""
from __future__ import annotations

import pytest


# ─── Greeting ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "привет",
    "Привет",
    "Привет!",
    "  привет  ",
    "Здравствуйте",
    "здравствуй",
    "Добрый день",
    "добрый вечер",
    "Доброе утро",
    "доброго дня",
    "hi",
    "Hello",
    "hey",
    "Здарова",
    "приветик",
    "приветствую",
])
def test_detect_intent_greeting(text):
    from maxbot.intents import detect_intent
    response = detect_intent(text)
    assert response is not None
    assert "Здравствуйте" in response or "Формула тела" in response


# ─── Thanks ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "спасибо",
    "Спасибо!",
    "СПАСИБО",
    "благодарю",
    "thanks",
    "thx",
])
def test_detect_intent_thanks(text):
    from maxbot.intents import detect_intent
    response = detect_intent(text)
    assert response is not None
    assert "пожалуйста" in response.lower() or "рад" in response.lower()


# ─── Small-talk ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "как дела",
    "Как дела?",
    "как ты",
    "что нового",
    "как поживаешь",
    "как жизнь",
])
def test_detect_intent_small_talk(text):
    from maxbot.intents import detect_intent
    response = detect_intent(text)
    assert response is not None
    # Бот должен направить к услугам — упоминание салона/услуг/помощи
    assert any(kw in response.lower() for kw in ("помог", "услуг", "запис", "салон"))


# ─── Real questions — НЕ matched ─────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "сколько стоит массаж спины",
    "как записаться",
    "режим работы",
    "где вы находитесь",
    "у вас есть подарочные сертификаты",
    "сколько длится массаж",
    "хочу записаться к Анне",
    "болит спина что выбрать",
])
def test_detect_intent_returns_none_on_real_question(text):
    """Реальные вопросы про салон должны идти через RAG, а не intent-router."""
    from maxbot.intents import detect_intent
    assert detect_intent(text) is None


# ─── Edge cases ────────────────────────────────────────────────────────────


def test_detect_intent_empty_string():
    from maxbot.intents import detect_intent
    assert detect_intent("") is None


def test_detect_intent_only_whitespace():
    from maxbot.intents import detect_intent
    assert detect_intent("   \n\t  ") is None


def test_detect_intent_greeting_then_question_not_matched():
    """Если вместе с приветствием задан реальный вопрос — пусть RAG обрабатывает.

    «привет, сколько стоит» — НЕ canned greeting (там есть содержательный вопрос).
    """
    from maxbot.intents import detect_intent
    assert detect_intent("привет, сколько стоит массаж спины") is None
