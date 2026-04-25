"""Response cache для AI-помощника MAX-бота."""
import pytest
from django.core.cache import cache

from maxbot.response_cache import (
    CACHE_KEY_PREFIX,
    CACHE_TTL_SECONDS,
    get_cached_answer,
    normalize_question,
    set_cached_answer,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


# ─── normalize_question ─────────────────────────────────────────────────────


def test_normalize_lowercase():
    assert normalize_question("КАК ЗАПИСАТЬСЯ") == "как записаться"


def test_normalize_strip_outer_whitespace():
    assert normalize_question("  как записаться  ") == "как записаться"


def test_normalize_collapse_inner_whitespace():
    assert normalize_question("как   записаться") == "как записаться"


def test_normalize_strips_trailing_punctuation():
    assert normalize_question("Как записаться?") == "как записаться"
    assert normalize_question("Как записаться!!!") == "как записаться"
    assert normalize_question("Как записаться.") == "как записаться"
    assert normalize_question("Как записаться ?  ") == "как записаться"


def test_normalize_keeps_inner_punctuation():
    """Внутренняя пунктуация (а не на конце) не съедается."""
    assert normalize_question("Сколько стоит, например, массаж?") == "сколько стоит, например, массаж"


def test_normalize_idempotent():
    once = normalize_question("Как Записаться?")
    twice = normalize_question(once)
    assert once == twice


def test_normalize_empty_string():
    assert normalize_question("") == ""
    assert normalize_question("   ") == ""


# ─── get_cached_answer / set_cached_answer ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_none_when_empty():
    assert await get_cached_answer("Что-то новое?") is None


@pytest.mark.asyncio
async def test_set_and_get_roundtrip():
    await set_cached_answer("Как записаться?", "Через бота или по телефону.")
    assert await get_cached_answer("Как записаться?") == "Через бота или по телефону."


@pytest.mark.asyncio
async def test_normalization_unifies_variants():
    """Все косметические варианты одного вопроса дают тот же ответ."""
    await set_cached_answer("Как записаться?", "ответ1")
    for variant in [
        "как записаться",
        "Как записаться",
        "как ЗАПИСАТЬСЯ?",
        "  как записаться  ",
        "Как записаться!",
        "как  записаться",
    ]:
        assert await get_cached_answer(variant) == "ответ1", f"variant={variant!r}"


@pytest.mark.asyncio
async def test_short_question_not_cached():
    """Слишком короткие вопросы не пишутся и не читаются."""
    await set_cached_answer("?", "не должно сохраниться")
    # set_cached_answer молча игнорирует — ключ не появился в кэше
    assert await get_cached_answer("?") is None


@pytest.mark.asyncio
async def test_short_question_after_normalization_not_cached():
    """Длинная строка из пунктуации/пробелов после нормализации = пусто → skip."""
    await set_cached_answer("   ?? !!  ", "не должно сохраниться")
    assert await get_cached_answer("   ?? !!  ") is None


@pytest.mark.asyncio
async def test_different_questions_isolated():
    await set_cached_answer("Как записаться?", "ответ A")
    await set_cached_answer("Сколько стоит массаж?", "ответ B")
    assert await get_cached_answer("Как записаться?") == "ответ A"
    assert await get_cached_answer("Сколько стоит массаж?") == "ответ B"


@pytest.mark.asyncio
async def test_set_uses_ttl(monkeypatch):
    """set_cached_answer передаёт CACHE_TTL_SECONDS в cache.set."""
    captured = {}

    def fake_set(key, value, timeout=None):
        captured["key"] = key
        captured["value"] = value
        captured["timeout"] = timeout

    monkeypatch.setattr(cache, "set", fake_set)
    await set_cached_answer("Какой ваш режим работы?", "9-21 без выходных")
    assert captured["timeout"] == CACHE_TTL_SECONDS
    assert captured["value"] == "9-21 без выходных"
    assert captured["key"].startswith(CACHE_KEY_PREFIX)
