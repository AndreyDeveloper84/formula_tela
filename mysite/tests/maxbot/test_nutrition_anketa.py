"""Phase 3.1 Part 1: TIER-A анкета — handlers тесты.

Используем fake-объекты вместо реального MAX SDK runtime: каждому handler'у
передаём (callback|event, MemoryContext). Контролируем `bot.send_message`
через AsyncMock и проверяем (chat_id, text, attachments).

Ayla calls (`upsert_profile`, `get_profile`) мокаем через
monkeypatch.setattr на singleton `get_nutrition_client()`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ─── helpers ───────────────────────────────────────────────────────────────


def _fake_callback(payload: str, chat_id: int = 12345) -> MagicMock:
    """Build minimal MessageCallback double для router-handler'а."""
    cb = MagicMock()
    cb.callback.payload = payload
    cb.message.recipient.chat_id = chat_id
    cb.bot.send_message = AsyncMock()
    return cb


def _fake_message(text: str, chat_id: int = 12345, sender_id: int = 99) -> MagicMock:
    """Build minimal MessageCreated double."""
    msg = MagicMock()
    msg.message.body.text = text
    msg.message.recipient.chat_id = chat_id
    msg.message.sender.user_id = sender_id
    msg.bot.send_message = AsyncMock()
    return msg


# ─── consent step ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_anketa_sets_consent_state_and_renders_disclaimer():
    """Юзер кликнул [📝 Настроить под себя] → state=awaiting_consent,
    бот шлёт текст дисклеймера + 2 кнопки."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_entry import on_start_anketa
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:nutrition:start_anketa", chat_id=12345)
    ctx = MemoryContext(chat_id=12345, user_id=99)

    await on_start_anketa(cb, ctx)

    state = await ctx.get_state()
    assert state == NutritionAnketaStates.awaiting_consent

    cb.bot.send_message.assert_awaited_once()
    call_kwargs = cb.bot.send_message.await_args.kwargs
    text_lower = call_kwargs["text"].lower()
    # Дисклеймер должен упоминать персональные данные или закон 152-ФЗ
    assert "152" in text_lower or "дисклеймер" in text_lower or "данн" in text_lower
    # Attachments — keyboard с 2 кнопками
    assert call_kwargs.get("attachments") is not None


# ─── consent OK / decline ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consent_ok_advances_to_gender_step():
    """Клик «✓ Понятно» → state=awaiting_gender, бот шлёт вопрос про пол."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_consent_ok
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:anketa:consent:ok")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_consent)

    await on_consent_ok(cb, ctx)

    assert await ctx.get_state() == NutritionAnketaStates.awaiting_gender
    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "пол" in text.lower()


@pytest.mark.asyncio
async def test_consent_decline_clears_state_and_exits():
    """Клик «Не сейчас» → state очищен, бот шлёт 'возвращайся когда будешь готова'."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_consent_decline
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:anketa:consent:decline")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_consent)

    await on_consent_decline(cb, ctx)

    assert await ctx.get_state() is None
    cb.bot.send_message.assert_awaited_once()


# ─── gender step ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gender_female_calls_ayla_upsert_with_gender_field(monkeypatch):
    """Клик «Женский» → upsert_profile вызван с gender=female + complete=False,
    state advances to awaiting_age."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_gender_female
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._client",
        lambda: fake_client,
    )

    # bot_user resolution mock
    bot_user_mock = MagicMock(max_user_id=99)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=bot_user_mock),
    )

    cb = _fake_callback("cb:anketa:gender:female")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_gender)

    await on_gender_female(cb, ctx)

    upsert_mock.assert_awaited_once()
    kwargs = upsert_mock.await_args.kwargs
    assert kwargs["external_user_id"] == "bot:99"
    assert kwargs["data"]["gender"] == "female"
    assert kwargs["data"]["complete"] is False

    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age


@pytest.mark.asyncio
async def test_gender_skip_sends_skipped_field_and_advances(monkeypatch):
    """Клик [⏭ Пропустить] на шаге gender → upsert с _skipped_fields=['gender']."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_skip
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    cb = _fake_callback("cb:anketa:skip")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_gender)

    await on_skip(cb, ctx)

    kwargs = upsert_mock.await_args.kwargs
    assert kwargs["data"]["_skipped_fields"] == ["gender"]
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age


# ─── age step (text-input) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_age_text_input_parses_and_advances(monkeypatch):
    """Юзер пишет «35» в state=awaiting_age → parse_age=35, upsert(age=35),
    state=awaiting_height."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_age_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("35")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_age_text(msg, ctx)

    assert upsert_mock.await_args.kwargs["data"]["age"] == 35
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_height


@pytest.mark.asyncio
async def test_age_text_input_refused_treats_as_skip(monkeypatch):
    """parse_age возвращает 'REFUSED' для «не скажу» → upsert как skip."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_age_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("не скажу")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_age_text(msg, ctx)

    assert upsert_mock.await_args.kwargs["data"]["_skipped_fields"] == ["age"]
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_height


@pytest.mark.asyncio
async def test_age_text_input_unparseable_asks_again(monkeypatch):
    """parse_age возвращает None для «абвгд» → НЕ переходим, просим повторить."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_age_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock()
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)

    msg = _fake_message("абвгд")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_age_text(msg, ctx)

    upsert_mock.assert_not_awaited()  # NO upsert
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age  # state same
    msg.bot.send_message.assert_awaited_once()
    text = msg.bot.send_message.await_args.kwargs["text"]
    assert "не понял" in text.lower() or "число" in text.lower()


@pytest.mark.asyncio
async def test_skip_button_works_at_age_state(monkeypatch):
    """Skip-кнопка на awaiting_age → upsert _skipped_fields=['age'],
    advance to awaiting_height."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_skip
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    cb = _fake_callback("cb:anketa:skip")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_skip(cb, ctx)

    assert upsert_mock.await_args.kwargs["data"]["_skipped_fields"] == ["age"]
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_height


# ─── height + weight (same shape as age) ───────────────────────────────────


@pytest.mark.asyncio
async def test_height_text_input_parses_and_advances(monkeypatch):
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_height_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("165")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_height)

    await on_height_text(msg, ctx)

    assert upsert_mock.await_args.kwargs["data"]["height_cm"] == 165
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_weight


@pytest.mark.asyncio
async def test_weight_text_input_with_range_stores_range_field(monkeypatch):
    """parse_weight возвращает {'value': None, 'range': '65-75', 'exact': False}
    для диапазона → upsert с weight_range, без weight_kg."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_weight_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("65-75")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_weight)

    await on_weight_text(msg, ctx)

    body = upsert_mock.await_args.kwargs["data"]
    assert body.get("weight_range") == "65-75"
    assert "weight_kg" not in body or body["weight_kg"] is None
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_goal


@pytest.mark.asyncio
async def test_weight_text_input_exact_value_advances_to_goal(monkeypatch):
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_weight_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("70")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_weight)

    await on_weight_text(msg, ctx)

    assert upsert_mock.await_args.kwargs["data"]["weight_kg"] == 70
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_goal


@pytest.mark.asyncio
async def test_height_text_input_refused_treats_as_skip(monkeypatch):
    """parse_height возвращает 'REFUSED' для «не скажу» → upsert как skip."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_height_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("не скажу")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_height)

    await on_height_text(msg, ctx)

    assert upsert_mock.await_args.kwargs["data"]["_skipped_fields"] == ["height"]
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_weight


@pytest.mark.asyncio
async def test_weight_text_input_refused_treats_as_skip(monkeypatch):
    """parse_weight возвращает 'REFUSED' для «не скажу» → upsert как skip."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_weight_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("не скажу")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_weight)

    await on_weight_text(msg, ctx)

    assert upsert_mock.await_args.kwargs["data"]["_skipped_fields"] == ["weight"]
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_goal
