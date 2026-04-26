"""maxbot.warmup — прогрев response cache при старте процесса бота."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.core.cache import cache


@pytest.fixture
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _patch_questions(qs: list[str]):
    """Подменяет POPULAR_QUESTIONS — позволяет тесту контролировать N."""
    return patch("maxbot.warmup.POPULAR_QUESTIONS", qs)


# ─── Базовая логика прогрева ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_warmup_caches_uncached_questions(_clear_cache):
    """Пустой cache → chat_rag вызван для каждого вопроса, ответы закэшированы."""
    from maxbot.response_cache import get_cached_answer
    from maxbot.warmup import warmup_response_cache

    questions = ["как записаться", "сколько стоит"]
    mcp_client = MagicMock()

    with _patch_questions(questions), \
         patch("maxbot.warmup.chat_rag", AsyncMock(return_value="ответ из кэша")) as mock_rag:
        await warmup_response_cache(mcp_client=mcp_client)

    assert mock_rag.await_count == 2
    for q in questions:
        assert await get_cached_answer(q) == "ответ из кэша"


@pytest.mark.asyncio
async def test_warmup_skips_already_cached(_clear_cache):
    """Cache уже содержит ответ — chat_rag НЕ вызывается (экономия)."""
    from maxbot.response_cache import set_cached_answer
    from maxbot.warmup import warmup_response_cache

    await set_cached_answer("как записаться", "уже в кэше")
    questions = ["как записаться", "сколько стоит"]
    mcp_client = MagicMock()

    with _patch_questions(questions), \
         patch("maxbot.warmup.chat_rag", AsyncMock(return_value="свежий ответ")) as mock_rag:
        await warmup_response_cache(mcp_client=mcp_client)

    # Только 1 chat_rag-вызов — для второго вопроса, не первого
    assert mock_rag.await_count == 1
    call_text = mock_rag.await_args.kwargs.get("user_text") or mock_rag.await_args.args[0]
    assert "сколько" in call_text


@pytest.mark.asyncio
async def test_warmup_does_not_cache_giveup(_clear_cache):
    """LLM_GIVEUP_MESSAGE не сохраняется — пусть retry даёт шанс."""
    from maxbot.llm import LLM_GIVEUP_MESSAGE
    from maxbot.response_cache import get_cached_answer
    from maxbot.warmup import warmup_response_cache

    questions = ["странный вопрос"]
    mcp_client = MagicMock()

    with _patch_questions(questions), \
         patch("maxbot.warmup.chat_rag", AsyncMock(return_value=LLM_GIVEUP_MESSAGE)):
        await warmup_response_cache(mcp_client=mcp_client)

    assert await get_cached_answer("странный вопрос") is None


# ─── Robustness ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_warmup_continues_after_exception(_clear_cache):
    """Exception на одном вопросе не блокирует остальные."""
    from maxbot.response_cache import get_cached_answer
    from maxbot.warmup import warmup_response_cache

    # ≥3 chars после нормализации (MIN_QUESTION_LEN в response_cache)
    questions = ["вопрос один", "вопрос два", "вопрос три"]
    # вопрос-два падает, остальные успешны
    side_effects = ["ответ один", RuntimeError("LLM blip"), "ответ три"]
    mcp_client = MagicMock()

    with _patch_questions(questions), \
         patch("maxbot.warmup.chat_rag", AsyncMock(side_effect=side_effects)):
        await warmup_response_cache(mcp_client=mcp_client)

    assert await get_cached_answer("вопрос один") == "ответ один"
    assert await get_cached_answer("вопрос два") is None  # exception
    assert await get_cached_answer("вопрос три") == "ответ три"


@pytest.mark.asyncio
async def test_warmup_returns_summary_counts(_clear_cache):
    """Функция возвращает (cached, skipped, failed) для логов и тестируемости."""
    from maxbot.response_cache import set_cached_answer
    from maxbot.warmup import warmup_response_cache

    await set_cached_answer("вопрос один", "уже в кэше")
    # один уже закэширован → skipped, два → cached, три → failed
    questions = ["вопрос один", "вопрос два", "вопрос три"]
    mcp_client = MagicMock()

    with _patch_questions(questions), \
         patch("maxbot.warmup.chat_rag",
               AsyncMock(side_effect=["new_a2", RuntimeError("boom")])):
        result = await warmup_response_cache(mcp_client=mcp_client)

    assert result == {"cached": 1, "skipped": 1, "failed": 1}


@pytest.mark.asyncio
async def test_warmup_with_empty_questions_is_noop(_clear_cache):
    """Пустой POPULAR_QUESTIONS → ноль вызовов, ноль падений."""
    from maxbot.warmup import warmup_response_cache

    mcp_client = MagicMock()
    with _patch_questions([]), \
         patch("maxbot.warmup.chat_rag", AsyncMock()) as mock_rag:
        result = await warmup_response_cache(mcp_client=mcp_client)

    mock_rag.assert_not_awaited()
    assert result == {"cached": 0, "skipped": 0, "failed": 0}


# ─── Sanity — POPULAR_QUESTIONS список ────────────────────────────────────


def test_popular_questions_nonempty_strings():
    from maxbot.popular_questions import POPULAR_QUESTIONS

    assert len(POPULAR_QUESTIONS) > 0
    assert all(isinstance(q, str) and q.strip() for q in POPULAR_QUESTIONS)
    # Защита от копипасты — хотим уникальный набор
    assert len(POPULAR_QUESTIONS) == len(set(POPULAR_QUESTIONS))
