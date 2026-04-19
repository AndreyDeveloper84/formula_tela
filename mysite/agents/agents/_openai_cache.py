"""OpenAI chat completion с кешированием через django.core.cache.

Кеш-ключ детерминированно выводится из (model, messages, response_format,
max_tokens, temperature). Одинаковый prompt → cache hit → 0 API calls.

Зачем:
- Защита от Celery retry (повторный вызов не тратит токены).
- Dev/staging тестирование без повторных расходов.
- Подушка безопасности при rate limits OpenAI.

Errors не кешируются — при API error исключение пробрасывается наверх.
"""
import hashlib
import json
import logging

from django.conf import settings
from django.core.cache import cache

from agents.agents import get_openai_client

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "openai:chat:"
DEFAULT_TTL = 86400  # 24 часа


def _build_cache_key(
    model: str,
    messages: list[dict],
    response_format: dict | None,
    max_tokens: int | None,
    temperature: float | None,
) -> str:
    """Собирает стабильный hash-ключ из параметров вызова."""
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "response_format": response_format,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.md5(payload).hexdigest()
    return f"{CACHE_KEY_PREFIX}{digest}"


def cached_chat_completion(
    messages: list[dict],
    *,
    model: str | None = None,
    response_format: dict | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    cache_ttl: int = DEFAULT_TTL,
    cache_bypass: bool = False,
) -> str:
    """Вызывает OpenAI chat completion с кешированием content-строки.

    Аргументы совпадают с `client.chat.completions.create(...)` (подмножество).
    Возвращает `response.choices[0].message.content.strip()`.

    - `cache_ttl` — TTL в секундах (default 24h).
    - `cache_bypass=True` — игнорировать кеш (для retry на SAME prompt).
    """
    effective_model = model or settings.OPENAI_MODEL
    cache_key = _build_cache_key(
        effective_model, messages, response_format, max_tokens, temperature
    )

    if not cache_bypass:
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info("OpenAI cache HIT: %s", cache_key[-16:])
            return cached

    client = get_openai_client()
    call_kwargs: dict = {"model": effective_model, "messages": messages}
    if response_format is not None:
        call_kwargs["response_format"] = response_format
    if max_tokens is not None:
        call_kwargs["max_tokens"] = max_tokens
    if temperature is not None:
        call_kwargs["temperature"] = temperature

    response = client.chat.completions.create(**call_kwargs)
    content = response.choices[0].message.content.strip()

    usage = getattr(response, "usage", None)
    if usage:
        logger.info(
            "OpenAI cache MISS: %s (in=%d out=%d total=%d)",
            cache_key[-16:],
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.total_tokens,
        )
    else:
        logger.info("OpenAI cache MISS: %s (no usage info)", cache_key[-16:])

    cache.set(cache_key, content, cache_ttl)
    return content
