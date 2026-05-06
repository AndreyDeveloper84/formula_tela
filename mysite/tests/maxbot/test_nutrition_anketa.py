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


# ─── goal step ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_goal_maintain_skips_pace_goes_to_complete(monkeypatch):
    """goal=maintain → нет pace, нет gain_clarify, нет BMI ladder → complete."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_maintain
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={"daily_kcal": 1450, "protein_g": 110, "fat_g": 50,
             "carbs_g": 145, "water_ml": 1900},
    ))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    cb = _fake_callback("cb:anketa:goal:maintain")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)

    await on_goal_maintain(cb, ctx)

    assert upsert_mock.await_args.kwargs["data"]["goal"] == "maintain"
    assert upsert_mock.await_args.kwargs["data"]["complete"] is True
    assert await ctx.get_state() == NutritionAnketaStates.complete


@pytest.mark.asyncio
async def test_goal_lose_normal_bmi_advances_to_pace(monkeypatch):
    """goal=lose, BMI=24 (норма) → state=awaiting_pace, НЕ ladder.
    upsert НЕ вызван — pace ещё не выбран, отложили."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_lose
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._fetch_profile_for_bmi",
        AsyncMock(return_value=(70, 170)),  # weight, height — BMI=24.2
    )

    cb = _fake_callback("cb:anketa:goal:lose")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)

    await on_goal_lose(cb, ctx)

    upsert_mock.assert_not_awaited()
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_pace


@pytest.mark.asyncio
async def test_goal_lose_low_bmi_triggers_ladder(monkeypatch):
    """goal=lose, BMI=17.6 (<18.5) → state=awaiting_bmi_ladder."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_lose
    from maxbot.states import NutritionAnketaStates

    fake_client = MagicMock()
    fake_client.upsert_profile = AsyncMock()
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._fetch_profile_for_bmi",
        AsyncMock(return_value=(48, 165)),  # BMI=17.6
    )

    cb = _fake_callback("cb:anketa:goal:lose")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)

    await on_goal_lose(cb, ctx)

    assert await ctx.get_state() == NutritionAnketaStates.awaiting_bmi_ladder


@pytest.mark.asyncio
async def test_goal_gain_advances_to_clarify(monkeypatch):
    """goal=gain → state=awaiting_gain_clarify (mass vs tone)."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_gain
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:anketa:goal:gain")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)

    await on_goal_gain(cb, ctx)

    assert await ctx.get_state() == NutritionAnketaStates.awaiting_gain_clarify


@pytest.mark.asyncio
async def test_goal_lose_no_profile_falls_through_to_pace(monkeypatch):
    """goal=lose без данных профиля (_fetch_profile_for_bmi=None) → state=awaiting_pace.
    Безопасный fallback: нет данных для BMI ladder, продолжаем в pace.
    """
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_lose
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock()
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._fetch_profile_for_bmi",
        AsyncMock(return_value=None),  # ← profile missing or invalid
    )

    cb = _fake_callback("cb:anketa:goal:lose")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)

    await on_goal_lose(cb, ctx)

    upsert_mock.assert_not_awaited()
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_pace


# ─── pace + gain_clarify + finalize render ─────────────────────────────────


@pytest.mark.asyncio
async def test_pace_moderate_calls_finalize_with_lose_moderate(monkeypatch):
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_pace_moderate
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={"daily_kcal": 1450, "protein_g": 110, "fat_g": 50,
             "carbs_g": 145, "water_ml": 1900,
             "goal_overridden_by": None, "overrides_applied": []},
        daily_kcal=1450, protein_g=110, fat_g=50, carbs_g=145, water_ml=1900,
        goal_overridden_by=None,
    ))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._mark_onboarded",
        AsyncMock(),
    )

    cb = _fake_callback("cb:anketa:pace:moderate")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_pace)

    await on_pace_moderate(cb, ctx)

    body = upsert_mock.await_args.kwargs["data"]
    assert body["goal"] == "lose"
    assert body["pace"] == "moderate"
    assert body["complete"] is True
    assert await ctx.get_state() == NutritionAnketaStates.complete


@pytest.mark.asyncio
async def test_gain_tone_finalizes_with_goal_tone(monkeypatch):
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_gain_tone
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={}, daily_kcal=1700, protein_g=130, fat_g=60, carbs_g=180,
        water_ml=2000, goal_overridden_by=None,
    ))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._mark_onboarded",
        AsyncMock(),
    )

    cb = _fake_callback("cb:anketa:gain:tone")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_gain_clarify)

    await on_gain_tone(cb, ctx)

    assert upsert_mock.await_args.kwargs["data"]["goal"] == "tone"


@pytest.mark.asyncio
async def test_finalize_renders_full_norms_screen(monkeypatch):
    """Финальный экран показывает: 🎯 ккал · Б Ж У · 💧 ml + кнопка
    [📸 Сфоткать первый приём]."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_pace_gentle
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={}, daily_kcal=1305, protein_g=110, fat_g=45, carbs_g=130,
        water_ml=1900, goal_overridden_by=None,
    ))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._mark_onboarded",
        AsyncMock(),
    )

    cb = _fake_callback("cb:anketa:pace:gentle")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_pace)

    await on_pace_gentle(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    # Формат: содержит ккал + БЖУ + воду
    assert "1305" in text
    assert "Б 110" in text
    assert "1900" in text or "1.9" in text
    # Кнопка фото есть
    assert cb.bot.send_message.await_args.kwargs.get("attachments") is not None


@pytest.mark.asyncio
async def test_finalize_marks_bot_user_onboarded(monkeypatch):
    """После complete — _mark_onboarded(bot_user) вызван."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_maintain
    from maxbot.states import NutritionAnketaStates

    bot_user = MagicMock(max_user_id=99, nutrition_onboarded_at=None)
    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={}, daily_kcal=1500, protein_g=100, fat_g=50, carbs_g=150,
        water_ml=2000, goal_overridden_by=None,
    ))
    mark_mock = AsyncMock()

    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=bot_user),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._mark_onboarded", mark_mock,
    )

    cb = _fake_callback("cb:anketa:goal:maintain")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)

    await on_goal_maintain(cb, ctx)

    mark_mock.assert_awaited_once_with(bot_user)


def test_format_complete_text_handles_null_water_ml():
    """Если Ayla вернула water_ml=None — рендер показывает 0 (не crash)."""
    from maxbot.handlers.nutrition_anketa import _format_complete_text

    profile = MagicMock(
        daily_kcal=1450, protein_g=110, fat_g=50, carbs_g=145, water_ml=None,
    )

    text = _format_complete_text(profile)
    assert "1450" in text
    assert "💧 0 мл" in text  # defensive fallback
    # Не падает — самое важное


# ─── BMI ladder ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bmi_doctor_button_clears_state_with_referral(monkeypatch):
    """[Хочу к врачу] → state cleared, бот шлёт текст референса в поликлинику.
    НЕ ведёт в салон (Design Doc §4.4)."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_bmi_doctor

    cb = _fake_callback("cb:anketa:bmi:doctor")
    ctx = MemoryContext(chat_id=12345, user_id=99)

    await on_bmi_doctor(cb, ctx)

    assert await ctx.get_state() is None
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "врач" in text.lower() or "поликлин" in text.lower() or \
           "эндокринолог" in text.lower()
    # НЕ должно быть упоминания салона
    assert "салон" not in text.lower()
    assert "массаж" not in text.lower()


@pytest.mark.asyncio
async def test_bmi_switch_maintain_finalizes_as_maintain(monkeypatch):
    """[Поменять на «держать»] → finalize с goal=maintain."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_bmi_switch_maintain
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={}, daily_kcal=1500, protein_g=100, fat_g=50, carbs_g=150,
        water_ml=2000, goal_overridden_by=None,
    ))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._mark_onboarded", AsyncMock(),
    )

    cb = _fake_callback("cb:anketa:bmi:switch_maintain")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_bmi_ladder)

    await on_bmi_switch_maintain(cb, ctx)

    assert upsert_mock.await_args.kwargs["data"]["goal"] == "maintain"
    assert await ctx.get_state() == NutritionAnketaStates.complete


@pytest.mark.asyncio
async def test_bmi_override_advances_to_pace_with_warning_flag(monkeypatch):
    """[Всё равно худеть] → advance to pace, помечаем bmi_warning_overridden."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_bmi_override
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    cb = _fake_callback("cb:anketa:bmi:override")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_bmi_ladder)

    await on_bmi_override(cb, ctx)

    body = upsert_mock.await_args.kwargs["data"]
    # Ayla получит флаг через health_flags.bmi_warning_overridden
    assert body.get("health_flags", {}).get("bmi_warning_overridden") is True
    assert body["complete"] is False
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_pace


# ─── overrides_applied render ──────────────────────────────────────────────


def test_format_complete_text_with_pregnancy_override():
    """Если ProfileResponse.goal_overridden_by='pregnancy' и goal стал
    maintain (был lose) — показываем блок 'Учла важное'."""
    from unittest.mock import MagicMock

    from maxbot.handlers.nutrition_anketa import _format_complete_text

    profile = MagicMock(
        daily_kcal=1650, protein_g=135, fat_g=55, carbs_g=160, water_ml=2000,
        goal_overridden_by="pregnancy",
        raw={
            "overrides_applied": [
                {"reason": "pregnancy",
                 "from": {"goal": "lose"},
                 "to": {"goal": "maintain"}},
            ],
        },
    )

    text = _format_complete_text(profile)
    assert "1650" in text
    assert "Учла важное" in text
    assert "беременн" in text.lower()


def test_format_complete_text_no_overrides_no_block():
    """Без overrides — нет блока 'Учла важное', только норма."""
    from unittest.mock import MagicMock

    from maxbot.handlers.nutrition_anketa import _format_complete_text

    profile = MagicMock(
        daily_kcal=1450, protein_g=110, fat_g=50, carbs_g=145, water_ml=1900,
        goal_overridden_by=None,
        raw={"overrides_applied": []},
    )

    text = _format_complete_text(profile)
    assert "Учла важное" not in text


def test_format_complete_text_with_bmr_floor_override():
    """goal_overridden_by='bmr_floor' → объяснение что подняли норму."""
    from unittest.mock import MagicMock

    from maxbot.handlers.nutrition_anketa import _format_complete_text

    profile = MagicMock(
        daily_kcal=1300, protein_g=110, fat_g=45, carbs_g=130, water_ml=1900,
        goal_overridden_by="bmr_floor",
        raw={
            "overrides_applied": [
                {"reason": "bmr_floor",
                 "from": {"pace": "moderate"},
                 "to": {"pace": "gentle"}},
            ],
        },
    )

    text = _format_complete_text(profile)
    assert "Учла важное" in text
    # Без термина BMR — метафора (Design Doc §4.4)
    assert "организм" in text.lower() or "ниже" in text.lower()


# ─── first meal CTA ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_meal_clears_state_and_hints_photo():
    """[📸 Сфоткать первый приём] → state cleared, бот шлёт hint про фото."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_first_meal
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:nutrition:first_meal")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.complete)

    await on_first_meal(cb, ctx)

    assert await ctx.get_state() is None
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "фото" in text.lower() or "сфотограф" in text.lower() or "пришли" in text.lower()


# ─── E2E happy path с ayla_mock ────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_e2e_anketa_happy_path_female_30_165_60_lose_moderate(monkeypatch):
    """Полный TIER-A flow: consent → female → 30 → 165 → 60 → lose → moderate.

    Используем in-memory ayla_mock как backend, проверяем что профиль
    в state.profiles содержит всё ожидаемое + BotUser.nutrition_onboarded_at
    установлен.
    """
    from asgiref.sync import sync_to_async

    from maxapi.context.context import MemoryContext

    from model_bakery import baker

    from maxbot.handlers.nutrition_anketa import (
        on_consent_ok,
        on_gender_female,
        on_age_text,
        on_height_text,
        on_weight_text,
        on_goal_lose,
        on_pace_moderate,
    )
    from maxbot.handlers.nutrition_entry import on_start_anketa
    from maxbot.states import NutritionAnketaStates
    from services_app.models import BotUser
    from tests.fixtures.ayla_mock import AylaMockState, install_mock_transport

    # ── Setup ──
    state = AylaMockState()
    install_mock_transport(monkeypatch, state)

    # install_mock_transport sets os.environ but NutritionClient reads from
    # Django settings (getattr(settings, "AYLA_BASE_URL", "")). Patch settings
    # directly so get_nutrition_client() can construct the singleton.
    from django.conf import settings as django_settings
    from django.test import override_settings
    monkeypatch.setattr(django_settings, "AYLA_BASE_URL", "http://ayla.test", raising=False)
    monkeypatch.setattr(django_settings, "NUTRITION_SERVICE_TOKEN", "test-token", raising=False)

    bot_user = await sync_to_async(baker.make)(
        BotUser,
        max_user_id=99,
        nutrition_onboarded_at=None,
    )

    # _resolve_bot_user обычно вызывает get_or_create_bot_user(sender_id) —
    # подменяем чтобы он вернул наш fixture'овский BotUser, не создавал
    # нового в БД через get_or_create. Нам важно что bot_user.save()
    # в _mark_onboarded реально пройдёт.
    from unittest.mock import AsyncMock
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=bot_user),
    )

    ctx = MemoryContext(chat_id=12345, user_id=99)

    # ── Step 1: enter anketa from welcome ──
    await on_start_anketa(_fake_callback("cb:nutrition:start_anketa"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_consent

    # ── Step 2: consent ──
    await on_consent_ok(_fake_callback("cb:anketa:consent:ok"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_gender

    # ── Step 3: gender=female ──
    await on_gender_female(_fake_callback("cb:anketa:gender:female"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age

    # ── Step 4: age=30 ──
    await on_age_text(_fake_message("30"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_height

    # ── Step 5: height=165 ──
    await on_height_text(_fake_message("165"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_weight

    # ── Step 6: weight=60 ──
    await on_weight_text(_fake_message("60"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_goal

    # ── Step 7: goal=lose (BMI=22 → норма, нет ladder) ──
    await on_goal_lose(_fake_callback("cb:anketa:goal:lose"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_pace

    # ── Step 8: pace=moderate → finalize ──
    await on_pace_moderate(_fake_callback("cb:anketa:pace:moderate"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.complete

    # ── Verify Ayla state ──
    profile = state.profiles.get("bot:99")
    assert profile is not None
    assert profile.gender == "female"
    assert profile.age == 30
    assert profile.height_cm == 165
    # weight may be int or Decimal depending on mock impl — accept either
    assert profile.weight_kg == 60 or profile.weight_kg == 60.0
    assert profile.goal == "lose"
    assert profile.pace == "moderate"

    # ── Verify BotUser.nutrition_onboarded_at установлен ──
    await sync_to_async(bot_user.refresh_from_db)()
    assert bot_user.nutrition_onboarded_at is not None

    # ── Verify finalize rendered Ayla-computed norms (not zero) ──
    # Guard against regression: Ayla spec §1.1 возвращает нормы под norms{} с daily_ префиксом.
    # BMR Mifflin-St Jeor для female 30/165/60 ≈ 1364; daily_kcal lose moderate (-15%) ≈ 1450.
    # Если парсер читает flat top-level — получаем 0 и юзер видит «Норма: 0 ккал».
    assert profile.daily_kcal > 0, (
        "daily_kcal=0 — парсер читает flat top-level вместо norms{daily_kcal} (Ayla spec §1.1)"
    )
    assert profile.daily_protein_g > 0, (
        "daily_protein_g=0 — парсер читает flat top-level вместо norms{daily_protein_g}"
    )


# ─── Regression: ValueError при пустом env не должен пробивать handler ─────


@pytest.mark.asyncio
async def test_upsert_misconfigured_env_shows_soft_message_not_crash(monkeypatch):
    """Прод-инцидент 2026-05-04: на staging .env не было AYLA_BASE_URL —
    `NutritionClient` ctor бросал ValueError, которая пробивалась через
    handler как HandlerException вместо мягкого сообщения юзеру.

    Defensive fix: _upsert ловит ValueError, показывает «Сервис временно
    недоступен», логирует ERROR — handler НЕ падает.
    """
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_gender_male
    from maxbot.states import NutritionAnketaStates

    def _client_misconfigured():
        raise ValueError("AYLA_BASE_URL is empty — nutrition client cannot start")

    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", _client_misconfigured)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    cb = _fake_callback("cb:anketa:gender:male")
    ctx = MemoryContext(chat_id=12345, user_id=99)
    await ctx.set_state(NutritionAnketaStates.awaiting_gender)

    # Не должно бросать ValueError
    await on_gender_male(cb, ctx)

    # Юзеру показано мягкое сообщение
    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "недоступен" in text.lower() or "позже" in text.lower()
    # State preserved (не clear, можно ретраить когда сервис вернётся)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_gender
