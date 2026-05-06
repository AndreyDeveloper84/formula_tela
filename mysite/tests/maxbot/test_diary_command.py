"""Phase 3.1 Part 2D.3 T03: /дневник opts in to with_comment=True."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_diary_command_calls_daily_summary_with_comment(monkeypatch):
    """Part 2D.3 T03: /дневник также запрашивает с with_comment=true."""
    from maxbot.handlers.food_scanner import on_diary_command
    from maxbot.services.nutrition_client import (
        SummaryResponse, WaterTodayResponse,
    )

    captured_kwargs = {}

    async def _capturing_summary(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return SummaryResponse(
            date="2026-05-05", calories_total=0, calories_goal=0,
            protein_g=0, fat_g=0, carbs_g=0, entries=[], raw={},
        )

    fake_client = MagicMock(
        daily_summary=_capturing_summary,
        get_water_today=AsyncMock(return_value=WaterTodayResponse(
            total_ml=0, norm_ml=2000, entries=[], raw={},
        )),
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )

    bot_user = MagicMock(max_user_id=42, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.external_user_id_for",
        lambda bu: "ext-42",
    )

    # Build a minimal MessageCreated stub
    bot = MagicMock()
    bot.send_message = AsyncMock()
    sender = MagicMock(user_id=42, full_name="Аня")
    recipient = MagicMock(chat_id=100)
    message = MagicMock(sender=sender, recipient=recipient)
    event = MagicMock(bot=bot, message=message)

    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.send_with_main_menu", AsyncMock(),
    )

    await on_diary_command(event, MagicMock())

    assert captured_kwargs.get("with_comment") is True
