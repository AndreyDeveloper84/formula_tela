"""Phase 3.2A T07: menopause + complete_tier_b с Ayla upsert + Учла важное."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from maxapi.context.context import MemoryContext

from maxbot.states import NutritionAnketaStates


def _cb(payload):
    cb = MagicMock()
    cb.callback.payload = payload
    cb.callback.user = MagicMock(user_id=200, full_name="Аня")
    cb.message.recipient.chat_id = 100
    cb.bot = MagicMock(send_message=AsyncMock())
    return cb


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,expected_value", [
    ("cb:tier_b:menopause:no", "no"),
    ("cb:tier_b:menopause:yes", "yes"),
    ("cb:tier_b:menopause:unsure", "unsure"),
    ("cb:tier_b:skip", "skipped"),
])
async def test_menopause_persists_and_completes(
    monkeypatch, payload, expected_value,
):
    from maxbot.handlers.health_screening import on_menopause_answer

    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    save_mock = MagicMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._persist_health_flag", save_mock,
    )
    complete_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.health_screening._complete_tier_b", complete_mock,
    )

    cb = _cb(payload)
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_menopause)

    await on_menopause_answer(cb, ctx)

    if payload == "cb:tier_b:skip":
        assert save_mock.call_args.args[1] == "menopause_skipped"
        assert save_mock.call_args.args[2] is True
    else:
        assert save_mock.call_args.args[1] == "menopause"
        assert save_mock.call_args.args[2] == expected_value
    complete_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_tier_b_calls_ayla_upsert_and_renders_overrides(monkeypatch):
    from maxbot.handlers.health_screening import _complete_tier_b
    from maxbot.services.nutrition_client import ProfileResponse

    bot_user = MagicMock(
        max_user_id=200,
        health_flags={
            "pregnant": True, "breastfeeding": False, "diabetes_type": "no",
            "chronic": [], "allergies": ["lactose"], "meds": False,
        },
    )

    fake_profile = ProfileResponse(
        gender="female", age=30, height_cm=165, weight_kg=60,
        goal="maintain", daily_kcal=1650, protein_g=135, fat_g=55,
        carbs_g=160, water_ml=2000, bmr=1300,
        health_flags={"pregnant": True, "allergies": ["lactose"]},
        disclaimer_acked=None,
        goal_overridden_by="pregnancy",
        raw={
            "overrides_applied": [
                "Беременность → цель «держать», +200 ккал, +25 г белка",
                "Аллергия на лактозу → исключаю из советов",
            ],
        },
    )

    fake_client = MagicMock(upsert_profile=AsyncMock(return_value=fake_profile))
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_nutrition_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.external_user_id_for",
        lambda bu: "ext-200",
    )

    bot = MagicMock(send_message=AsyncMock())
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_menopause)

    await _complete_tier_b(bot=bot, chat_id=100, bot_user=bot_user, context=ctx)

    # Ayla upsert called with health_flags payload
    fake_client.upsert_profile.assert_awaited_once()
    call_kwargs = fake_client.upsert_profile.await_args.kwargs
    assert call_kwargs["external_user_id"] == "ext-200"
    payload = call_kwargs["data"]
    assert payload.get("pregnant") is True
    assert payload.get("allergies") == ["lactose"]

    # Send shows «Учла важное» block + updated norms
    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.kwargs.get("text") or ""
    assert "Готово" in text
    assert "Учла важное" in text
    assert "1650" in text  # updated kcal
    assert "Беременность" in text

    # State cleared
    state = await ctx.get_state()
    assert state is None


@pytest.mark.asyncio
async def test_complete_tier_b_no_overrides_simple_message(monkeypatch):
    """Все health-флаги false → render_overrides_applied returns None →
    бот шлёт упрощённое «Готово ✓ Учту при советах.»"""
    from maxbot.handlers.health_screening import _complete_tier_b
    from maxbot.services.nutrition_client import ProfileResponse

    bot_user = MagicMock(max_user_id=200, health_flags={})
    fake_profile = ProfileResponse(
        gender="female", age=30, height_cm=165, weight_kg=60,
        goal="lose", daily_kcal=1450, protein_g=110, fat_g=50,
        carbs_g=145, water_ml=1900, bmr=1300,
        health_flags={}, disclaimer_acked=None,
        goal_overridden_by=None, raw={},
    )

    fake_client = MagicMock(upsert_profile=AsyncMock(return_value=fake_profile))
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_nutrition_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.external_user_id_for",
        lambda bu: "ext-200",
    )

    bot = MagicMock(send_message=AsyncMock())
    ctx = MemoryContext(chat_id=100, user_id=200)

    await _complete_tier_b(bot=bot, chat_id=100, bot_user=bot_user, context=ctx)

    text = bot.send_message.await_args.kwargs.get("text") or ""
    assert "Готово" in text
    assert "Учла важное" not in text


@pytest.mark.asyncio
async def test_complete_tier_b_ayla_failure_graceful(monkeypatch):
    """Ayla upsert → NutritionUnavailableError → бот всё равно clean'ит state +
    шлёт fallback «Сохранила, советы появятся позже»."""
    from maxbot.handlers.health_screening import _complete_tier_b
    from maxbot.services.nutrition_client import NutritionUnavailableError

    bot_user = MagicMock(max_user_id=200, health_flags={"pregnant": True})

    fake_client = MagicMock(
        upsert_profile=AsyncMock(side_effect=NutritionUnavailableError("circuit_open")),
    )
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.get_nutrition_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        "maxbot.handlers.health_screening.external_user_id_for",
        lambda bu: "ext-200",
    )

    bot = MagicMock(send_message=AsyncMock())
    ctx = MemoryContext(chat_id=100, user_id=200)

    await _complete_tier_b(bot=bot, chat_id=100, bot_user=bot_user, context=ctx)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.kwargs.get("text") or ""
    assert "Сохранила" in text or "позже" in text or "позже" in text.lower()
    state = await ctx.get_state()
    assert state is None
