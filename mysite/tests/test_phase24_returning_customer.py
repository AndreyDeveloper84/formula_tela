"""Phase 2.4 T05 — returning customer recognition."""
from __future__ import annotations

from datetime import date

import pytest
from asgiref.sync import sync_to_async
from model_bakery import baker

from services_app.models import BookingRequest, BotUser


# ─── get_client_history ───────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_client_history_new_user_empty():
    """Новый клиент — bookings_count=0, last_visits=[]."""
    from maxbot.personalization import get_client_history

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=1001)
    h = await get_client_history(bu)
    assert h["bookings_count"] == 0
    assert h["last_visits"] == []


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_client_history_returning_user():
    from maxbot.personalization import get_client_history

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=1002)
    # 3 успешных + 1 неудачная → bookings_count=3
    await sync_to_async(baker.make)(
        BookingRequest, bot_user=bu, is_processed=True,
        master_name="Анна", service_name="Массаж спины",
    )
    await sync_to_async(baker.make)(
        BookingRequest, bot_user=bu, is_processed=True,
        master_name="Мария", service_name="Релакс",
    )
    await sync_to_async(baker.make)(
        BookingRequest, bot_user=bu, is_processed=True,
        master_name="Анна", service_name="Лимфодренаж",
    )
    await sync_to_async(baker.make)(
        BookingRequest, bot_user=bu, is_processed=False,
        master_name="X", service_name="Y",
    )

    h = await get_client_history(bu)
    assert h["bookings_count"] == 3
    assert len(h["last_visits"]) == 3
    # Записи отсортированы -created_at: последняя добавленная — первая
    services = [v["service"] for v in h["last_visits"]]
    assert "Массаж спины" in services
    assert "Релакс" in services
    assert "Лимфодренаж" in services


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_client_history_caps_at_3_visits():
    """last_visits ограничен 3 записями (топ-3 свежих)."""
    from maxbot.personalization import get_client_history

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=1003)
    for i in range(5):
        await sync_to_async(baker.make)(
            BookingRequest, bot_user=bu, is_processed=True,
            master_name=f"M{i}", service_name=f"S{i}",
        )

    h = await get_client_history(bu)
    assert h["bookings_count"] == 5
    assert len(h["last_visits"]) == 3


# ─── render_system_prompt с last_visits ───────────────────────────────────


def test_prompt_no_history_block_for_new_user():
    """Если last_visits=[] — секция «ИСТОРИЯ КЛИЕНТА (последние визиты...)»
    не вставляется. Само словосочетание «ИСТОРИЯ КЛИЕНТА» в prompt rule 8
    остаётся — это ожидаемо."""
    from maxbot.ai_context import MasterContext
    from maxbot.ai_prompts import render_system_prompt

    ctx = MasterContext(
        candidates=[], candidate_ids=frozenset(),
        candidate_service_ids=frozenset(), summary_text="(тест)",
    )
    prompt = render_system_prompt(
        today=date(2026, 4, 29),
        client_name="Алиса",
        bookings_count=0,
        master_context=ctx,
        last_visits=[],
    )
    # Маркер блока с визитами (header) — не вставлен
    assert "ИСТОРИЯ КЛИЕНТА (последние визиты" not in prompt


def test_prompt_with_history_renders_visits():
    """last_visits → блок «ИСТОРИЯ КЛИЕНТА» с тремя визитами."""
    from maxbot.ai_context import MasterContext
    from maxbot.ai_prompts import render_system_prompt

    ctx = MasterContext(
        candidates=[], candidate_ids=frozenset(),
        candidate_service_ids=frozenset(), summary_text="(тест)",
    )
    prompt = render_system_prompt(
        today=date(2026, 4, 29),
        client_name="Алиса",
        bookings_count=3,
        master_context=ctx,
        last_visits=[
            {"date": "15.04.2026", "master": "Анна", "service": "Массаж спины"},
            {"date": "02.04.2026", "master": "Мария", "service": "Релакс"},
        ],
    )
    assert "ИСТОРИЯ КЛИЕНТА" in prompt
    assert "Анна" in prompt
    assert "Массаж спины" in prompt
    assert "Релакс" in prompt
    assert "15.04.2026" in prompt


def test_prompt_caps_history_at_3():
    from maxbot.ai_context import MasterContext
    from maxbot.ai_prompts import render_system_prompt

    ctx = MasterContext(
        candidates=[], candidate_ids=frozenset(),
        candidate_service_ids=frozenset(), summary_text="(тест)",
    )
    visits = [
        {"date": f"{i:02d}.04.2026", "master": f"M{i}", "service": f"S{i}"}
        for i in range(1, 6)
    ]
    prompt = render_system_prompt(
        today=date(2026, 4, 29),
        client_name="X",
        bookings_count=5,
        master_context=ctx,
        last_visits=visits,
    )
    # Только первые 3
    assert "S1" in prompt
    assert "S2" in prompt
    assert "S3" in prompt
    assert "S4" not in prompt
    assert "S5" not in prompt


def test_prompt_history_rule_in_template():
    """Sanity: rule 8 содержит инструкцию про ИСТОРИЯ КЛИЕНТА."""
    from maxbot.ai_context import MasterContext
    from maxbot.ai_prompts import render_system_prompt

    ctx = MasterContext(
        candidates=[], candidate_ids=frozenset(),
        candidate_service_ids=frozenset(), summary_text="(тест)",
    )
    prompt = render_system_prompt(
        today=date(2026, 4, 29),
        client_name="X",
        bookings_count=0,
        master_context=ctx,
    )
    assert "ИСТОРИЯ КЛИЕНТА" in prompt or "истори" in prompt.lower()
