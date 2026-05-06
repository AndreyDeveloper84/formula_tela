"""Phase 3.2A T08: ai_assistant pre-hook — health-signal triggers TIER-B."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from maxapi.context.context import MemoryContext

from maxbot.ai_context import MasterContext


@pytest.mark.asyncio
async def test_health_signal_triggers_screening_when_not_consented(monkeypatch, settings):
    """Free-text «беременная» → bot предлагает screening, AI Concierge НЕ запускается."""
    settings.NUTRITION_ENABLED = True
    from maxbot.handlers.ai_assistant import on_free_text

    bot_user = MagicMock(
        max_user_id=200, nutrition_onboarded_at=None, health_flags={},
    )
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    start_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.start_health_screening", start_mock,
    )
    concierge_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._invoke_ai_concierge", concierge_mock,
    )

    event = MagicMock()
    event.message.body.text = "Я беременная, что мне можно есть?"
    event.message.recipient.chat_id = 100
    event.message.sender = MagicMock(user_id=200, full_name="Аня")
    event.bot = MagicMock(send_message=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_free_text(event, ctx)

    start_mock.assert_awaited_once()
    concierge_mock.assert_not_called()


@pytest.mark.asyncio
async def test_health_signal_skipped_when_already_consented(monkeypatch, settings):
    """User уже прошёл health screening → free-text идёт в AI Concierge как обычно."""
    settings.NUTRITION_ENABLED = True
    from maxbot.handlers.ai_assistant import on_free_text

    bot_user = MagicMock(
        max_user_id=200, nutrition_onboarded_at="2026-04-30T12:00:00Z",
        health_flags={"health_consent_acked_at": "2026-05-01T10:00:00Z"},
    )
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    start_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.start_health_screening", start_mock,
    )
    concierge_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._invoke_ai_concierge", concierge_mock,
    )

    event = MagicMock()
    event.message.body.text = "Я беременная, что мне можно?"
    event.message.recipient.chat_id = 100
    event.message.sender = MagicMock(user_id=200, full_name="Аня")
    event.bot = MagicMock(send_message=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_free_text(event, ctx)

    start_mock.assert_not_called()
    concierge_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_signal_skipped_when_declined(monkeypatch, settings):
    """User declined health screening → не предлагать снова, идти в degraded AI."""
    settings.NUTRITION_ENABLED = True
    from maxbot.handlers.ai_assistant import on_free_text

    bot_user = MagicMock(
        max_user_id=200, nutrition_onboarded_at="2026-04-30T12:00:00Z",
        health_flags={"health_consent_declined_at": "2026-05-01T10:00:00Z"},
    )
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    start_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.start_health_screening", start_mock,
    )
    concierge_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._invoke_ai_concierge", concierge_mock,
    )

    event = MagicMock()
    event.message.body.text = "беременная"
    event.message.recipient.chat_id = 100
    event.message.sender = MagicMock(user_id=200, full_name="Аня")
    event.bot = MagicMock(send_message=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_free_text(event, ctx)

    start_mock.assert_not_called()
    concierge_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_signal_skipped_when_nutrition_disabled(monkeypatch, settings):
    """PR #135 pre-flight fix: NUTRITION_ENABLED=False → skip TIER-B trigger
    полностью, AI отвечает на запрос как обычно. Защищает прод-окружение
    с пустым AYLA_BASE_URL от ValueError в _complete_tier_b."""
    settings.NUTRITION_ENABLED = False
    from maxbot.handlers.ai_assistant import on_free_text

    bot_user = MagicMock(
        max_user_id=200, nutrition_onboarded_at=None, health_flags={},
    )
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    start_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.start_health_screening", start_mock,
    )
    concierge_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._invoke_ai_concierge", concierge_mock,
    )

    event = MagicMock()
    event.message.body.text = "Я беременная"
    event.message.recipient.chat_id = 100
    event.message.sender = MagicMock(user_id=200, full_name="Аня")
    event.bot = MagicMock(send_message=AsyncMock())

    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_free_text(event, ctx)

    start_mock.assert_not_called()
    concierge_mock.assert_awaited_once()


def _make_master_context() -> MasterContext:
    """Минимальный MasterContext для unit-теста render_system_prompt."""
    return MasterContext(
        candidates=[],
        candidate_ids=frozenset(),
        candidate_service_ids=frozenset(),
        summary_text="(тест)",
    )


def test_render_system_prompt_appends_degraded_note():
    """Phase 3.2A: advice_mode='degraded' → prompt содержит warning."""
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 5, 5), client_name="Аня", bookings_count=0,
        master_context=_make_master_context(), last_visits=[],
        advice_mode="degraded",
    )
    text = prompt.lower()
    assert "screening" in text or "скрининг" in text or "уточнен" in text
    # Should explicitly forbid personalized nutrition advice
    assert "не дав" in text or "без персональн" in text


def test_render_system_prompt_default_mode_no_degraded_note():
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today=date(2026, 5, 5), client_name="Аня", bookings_count=0,
        master_context=_make_master_context(), last_visits=[],
        advice_mode="full",
    )
    # Default mode does not contain the degraded-advice marker block.
    # Note: base prompt rule 12 already mentions «health screening» for
    # service contraindications, so we check the unique degraded marker
    # «degraded-advice» that only the new block adds.
    assert "degraded-advice" not in prompt.lower()
