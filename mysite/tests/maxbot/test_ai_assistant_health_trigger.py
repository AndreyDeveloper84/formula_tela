"""Phase 3.2A T08: ai_assistant pre-hook — health-signal triggers TIER-B."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_health_signal_triggers_screening_when_not_consented(monkeypatch):
    """Free-text «беременная» → bot предлагает screening, AI Concierge НЕ запускается."""
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

    await on_free_text(event, MagicMock())

    start_mock.assert_awaited_once()
    concierge_mock.assert_not_called()


@pytest.mark.asyncio
async def test_health_signal_skipped_when_already_consented(monkeypatch):
    """User уже прошёл health screening → free-text идёт в AI Concierge как обычно."""
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

    await on_free_text(event, MagicMock())

    start_mock.assert_not_called()
    concierge_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_signal_skipped_when_declined(monkeypatch):
    """User declined health screening → не предлагать снова, идти в degraded AI."""
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

    await on_free_text(event, MagicMock())

    start_mock.assert_not_called()
    concierge_mock.assert_awaited_once()


def test_render_system_prompt_appends_degraded_note():
    """Phase 3.2A: advice_mode='degraded' → prompt содержит warning."""
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today="2026-05-05", client_name="Аня", bookings_count=0,
        master_context="...", last_visits=[], advice_mode="degraded",
    )
    text = prompt.lower()
    assert "screening" in text or "скрининг" in text or "уточнен" in text
    # Should explicitly forbid personalized nutrition advice
    assert "не дав" in text or "без персональн" in text


def test_render_system_prompt_default_mode_no_degraded_note():
    from maxbot.ai_prompts import render_system_prompt
    prompt = render_system_prompt(
        today="2026-05-05", client_name="Аня", bookings_count=0,
        master_context="...", last_visits=[], advice_mode="full",
    )
    # Default mode does not contain the degraded-advice marker block.
    # Note: base prompt rule 12 already mentions «health screening» for
    # service contraindications, so we check the unique degraded marker
    # «degraded-advice» that only the new block adds.
    assert "degraded-advice" not in prompt.lower()
