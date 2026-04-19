"""Тесты cached_chat_completion: hit/miss, стабильность ключа, errors не кешируются."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache

from agents.agents._openai_cache import (
    CACHE_KEY_PREFIX,
    _build_cache_key,
    cached_chat_completion,
)


def _mock_response(content: str, *, prompt_tokens=50, completion_tokens=30):
    """Собирает MagicMock со структурой OpenAI chat completion response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    """Каждому тесту — чистый кеш."""
    cache.clear()
    yield
    cache.clear()


# ── _build_cache_key ───────────────────────────────────────────────────────

def test_cache_key_stable_for_same_inputs():
    k1 = _build_cache_key("gpt-4o-mini", [{"role": "user", "content": "привет"}], None, 100, None)
    k2 = _build_cache_key("gpt-4o-mini", [{"role": "user", "content": "привет"}], None, 100, None)
    assert k1 == k2
    assert k1.startswith(CACHE_KEY_PREFIX)


def test_cache_key_differs_for_different_messages():
    k1 = _build_cache_key("gpt-4o-mini", [{"role": "user", "content": "a"}], None, None, None)
    k2 = _build_cache_key("gpt-4o-mini", [{"role": "user", "content": "b"}], None, None, None)
    assert k1 != k2


def test_cache_key_differs_for_different_model():
    msgs = [{"role": "user", "content": "x"}]
    assert _build_cache_key("gpt-4o-mini", msgs, None, None, None) != \
           _build_cache_key("gpt-4o", msgs, None, None, None)


def test_cache_key_differs_for_different_response_format():
    msgs = [{"role": "user", "content": "x"}]
    assert _build_cache_key("m", msgs, None, None, None) != \
           _build_cache_key("m", msgs, {"type": "json_object"}, None, None)


def test_cache_key_differs_for_different_temperature():
    msgs = [{"role": "user", "content": "x"}]
    assert _build_cache_key("m", msgs, None, None, 0.0) != \
           _build_cache_key("m", msgs, None, None, 0.7)


# ── cached_chat_completion: HIT/MISS ───────────────────────────────────────

@patch("agents.agents._openai_cache.get_openai_client")
def test_first_call_hits_api_and_caches(mock_client_fn):
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_response("ответ-1")
    mock_client_fn.return_value = client

    result = cached_chat_completion(
        [{"role": "user", "content": "тест"}],
        model="gpt-4o-mini",
    )

    assert result == "ответ-1"
    assert client.chat.completions.create.call_count == 1


@patch("agents.agents._openai_cache.get_openai_client")
def test_second_call_same_prompt_uses_cache(mock_client_fn):
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_response("ответ-1")
    mock_client_fn.return_value = client

    msgs = [{"role": "user", "content": "тест"}]
    r1 = cached_chat_completion(msgs, model="gpt-4o-mini")
    r2 = cached_chat_completion(msgs, model="gpt-4o-mini")

    assert r1 == r2 == "ответ-1"
    assert client.chat.completions.create.call_count == 1  # 2-й вызов = HIT


@patch("agents.agents._openai_cache.get_openai_client")
def test_different_prompts_make_separate_calls(mock_client_fn):
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _mock_response("A"),
        _mock_response("B"),
    ]
    mock_client_fn.return_value = client

    r1 = cached_chat_completion([{"role": "user", "content": "prompt-1"}], model="m")
    r2 = cached_chat_completion([{"role": "user", "content": "prompt-2"}], model="m")

    assert r1 == "A"
    assert r2 == "B"
    assert client.chat.completions.create.call_count == 2


@patch("agents.agents._openai_cache.get_openai_client")
def test_cache_bypass_forces_api_call(mock_client_fn):
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_response("live")
    mock_client_fn.return_value = client

    msgs = [{"role": "user", "content": "x"}]
    cached_chat_completion(msgs, model="m")  # MISS → cache
    cached_chat_completion(msgs, model="m", cache_bypass=True)  # принудительный API call

    assert client.chat.completions.create.call_count == 2


# ── Errors не кешируются ───────────────────────────────────────────────────

@patch("agents.agents._openai_cache.get_openai_client")
def test_api_error_is_not_cached(mock_client_fn):
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        RuntimeError("rate limit"),
        _mock_response("после ретрая"),
    ]
    mock_client_fn.return_value = client

    msgs = [{"role": "user", "content": "x"}]
    with pytest.raises(RuntimeError):
        cached_chat_completion(msgs, model="m")

    # Повторный вызов — второй раз API call, не cache
    result = cached_chat_completion(msgs, model="m")
    assert result == "после ретрая"
    assert client.chat.completions.create.call_count == 2


# ── Передача параметров в OpenAI ──────────────────────────────────────────

@patch("agents.agents._openai_cache.get_openai_client")
def test_passes_response_format_and_max_tokens(mock_client_fn):
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_response("{}")
    mock_client_fn.return_value = client

    cached_chat_completion(
        [{"role": "user", "content": "x"}],
        model="m",
        response_format={"type": "json_object"},
        max_tokens=500,
        temperature=0.7,
    )

    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["max_tokens"] == 500
    assert call_kwargs["temperature"] == 0.7
    assert call_kwargs["model"] == "m"


@patch("agents.agents._openai_cache.get_openai_client")
def test_model_defaults_to_settings(mock_client_fn, settings):
    settings.OPENAI_MODEL = "gpt-4o-mini-default"
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_response("ok")
    mock_client_fn.return_value = client

    cached_chat_completion([{"role": "user", "content": "x"}])

    assert client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o-mini-default"


@patch("agents.agents._openai_cache.get_openai_client")
def test_content_is_stripped(mock_client_fn):
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_response("  \n  ответ  \n  ")
    mock_client_fn.return_value = client

    result = cached_chat_completion([{"role": "user", "content": "x"}], model="m")
    assert result == "ответ"
