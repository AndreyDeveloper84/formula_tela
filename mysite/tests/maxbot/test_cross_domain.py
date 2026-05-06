"""DRF-274 (B-4): cross-domain insights bot integration.

Tests cover:
- nutrition_client: get/seen/dismiss/convert methods (envelope handling, 404, 5xx).
- handlers/cross_domain: render_cross_domain_card + 3 callback handlers.
- food_scanner hook: feature flag, eating_disorder gate, best-effort error swallow.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from maxbot.services.nutrition_client import (
    NutritionAPIError,
    NutritionClient,
    NutritionUnavailableError,
    reset_nutrition_client,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_nutrition_client()
    yield
    reset_nutrition_client()


def _make_client(transport: httpx.MockTransport) -> NutritionClient:
    """Build a client whose internal httpx.AsyncClient uses a mock transport."""
    client = NutritionClient(
        base_url="http://ayla.test",
        service_token="test-token",
        timeout_s=2.0,
    )
    original = httpx.AsyncClient

    class _PatchedClient(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = _PatchedClient  # type: ignore[misc]
    client._reset_httpx = lambda: setattr(httpx, "AsyncClient", original)
    return client


def _ok_envelope(data: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"data": data})


# ─── nutrition_client.get_cross_domain_insights ────────────────────────────


def _full_insight_payload() -> dict:
    return {
        "has_insight": True,
        "insight": {
            "shown_id": "7c5f3b29-baea-4c1b-b94a-4606e68ba5cc",
            "rule_slug": "vitamin_d_deficit_to_argan_massage",
            "insight_text": "у тебя дефицит витамина D",
            "rationale_text": "стресс снижает уровень витамина D",
            "service_category_slug": "massage",
            "disclaimer_text": "это не медицинская рекомендация",
        },
    }


async def test_get_cross_domain_no_insight_returns_none():
    transport = httpx.MockTransport(
        lambda r: _ok_envelope({"has_insight": False})
    )
    client = _make_client(transport)
    try:
        result = await client.get_cross_domain_insights(external_user_id="bot:1")
    finally:
        client._reset_httpx()

    assert result is None


async def test_get_cross_domain_404_returns_none():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
    )
    client = _make_client(transport)
    try:
        result = await client.get_cross_domain_insights(external_user_id="bot:1")
    finally:
        client._reset_httpx()

    assert result is None


async def test_get_cross_domain_5xx_raises_unavailable():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(500, text="boom")
    )
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionUnavailableError):
            await client.get_cross_domain_insights(external_user_id="bot:1")
    finally:
        client._reset_httpx()


async def test_get_cross_domain_success_returns_dataclass():
    transport = httpx.MockTransport(
        lambda r: _ok_envelope(_full_insight_payload())
    )
    client = _make_client(transport)
    try:
        insight = await client.get_cross_domain_insights(external_user_id="bot:1")
    finally:
        client._reset_httpx()

    assert insight is not None
    assert insight.shown_id == "7c5f3b29-baea-4c1b-b94a-4606e68ba5cc"
    assert insight.rule_slug == "vitamin_d_deficit_to_argan_massage"
    assert "дефицит" in insight.insight_text
    assert insight.service_category_slug == "massage"
    assert "не медицинская" in insight.disclaimer_text


async def test_get_cross_domain_carries_service_token_and_external_id():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("X-Service-Token", "")
        seen["external_id"] = request.headers.get("X-External-User-ID", "")
        seen["path"] = request.url.path
        return _ok_envelope({"has_insight": False})

    client = _make_client(httpx.MockTransport(handler))
    try:
        await client.get_cross_domain_insights(external_user_id="bot:42")
    finally:
        client._reset_httpx()

    assert seen["token"] == "test-token"
    assert seen["external_id"] == "bot:42"
    assert "/api/v1/nutrition/internal/insights/cross_domain/" in seen["path"]


async def test_post_cross_domain_seen_returns_true_on_2xx():
    transport = httpx.MockTransport(lambda r: httpx.Response(204))
    client = _make_client(transport)
    try:
        ok = await client.post_cross_domain_seen(
            external_user_id="bot:1", shown_id="abc",
        )
    finally:
        client._reset_httpx()

    assert ok is True


async def test_post_cross_domain_dismiss_returns_true_on_2xx():
    seen_path: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_path["path"] = request.url.path
        return httpx.Response(200, json={"data": {}})

    client = _make_client(httpx.MockTransport(handler))
    try:
        ok = await client.post_cross_domain_dismiss(
            external_user_id="bot:1", shown_id="abc-123",
        )
    finally:
        client._reset_httpx()

    assert ok is True
    assert "/api/v1/nutrition/internal/insights/cross_domain/dismiss/abc-123/" in seen_path["path"]


async def test_post_cross_domain_convert_sends_appointment_id():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(200, json={"data": {"converted": True}})

    client = _make_client(httpx.MockTransport(handler))
    try:
        ok = await client.post_cross_domain_convert(
            external_user_id="bot:1",
            shown_id="abc-123",
            appointment_id="appt-9",
        )
    finally:
        client._reset_httpx()

    assert ok is True
    assert "/api/v1/nutrition/internal/insights/cross_domain/convert/abc-123/" in seen["path"]
    assert b"appt-9" in seen["body"]


async def test_post_cross_domain_dismiss_5xx_raises_unavailable():
    transport = httpx.MockTransport(lambda r: httpx.Response(503))
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionUnavailableError):
            await client.post_cross_domain_dismiss(
                external_user_id="bot:1", shown_id="abc",
            )
    finally:
        client._reset_httpx()


# ─── render_cross_domain_card ──────────────────────────────────────────────


def _make_insight():
    from maxbot.services.nutrition_client import CrossDomainInsight
    return CrossDomainInsight(
        shown_id="abc-123",
        rule_slug="vitamin_d",
        insight_text="у тебя дефицит витамина D",
        rationale_text="мало солнца зимой",
        service_category_slug="massage",
        disclaimer_text="это не медицинский совет",
    )


async def test_render_card_includes_disclaimer_in_italic():
    from maxbot.handlers.cross_domain import render_cross_domain_card

    text, attachments = render_cross_domain_card(_make_insight())

    assert "дефицит" in text
    assert "мало солнца" in text
    # Disclaimer rendered in italic markdown on a separate line
    assert "_это не медицинский совет_" in text
    # Buttons exist
    assert attachments
    inline = [a for a in attachments if getattr(a, "type", None) == "inline_keyboard"]
    assert len(inline) == 1
    payloads: list[str] = []
    for row in inline[0].payload.buttons:
        for btn in row:
            if hasattr(btn, "payload") and btn.payload:
                payloads.append(btn.payload)
    assert any(p == "cb:cross:convert:abc-123" for p in payloads)
    assert any(p == "cb:cross:dismiss:abc-123" for p in payloads)


# ─── Callback handlers ─────────────────────────────────────────────────────


def _make_callback(*, chat_id: int = 100, user_id: int = 200, payload: str = ""):
    user = MagicMock()
    user.user_id = user_id
    user.first_name = "Иван"
    user.full_name = "Иван"
    event = MagicMock()
    event.message = MagicMock()
    event.message.recipient = MagicMock()
    event.message.recipient.chat_id = chat_id
    event.callback = MagicMock()
    event.callback.user = user
    event.callback.payload = payload
    event.bot = MagicMock()
    event.bot.send_message = AsyncMock()
    event.bot.edit_message = AsyncMock()
    return event


@pytest.mark.django_db(transaction=True)
async def test_dismiss_callback_posts_dismiss():
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.cross_domain import on_dismiss

    event = _make_callback(payload="cb:cross:dismiss:abc-123", user_id=30001)
    ctx = MemoryContext(chat_id=100, user_id=30001)

    fake_client = MagicMock()
    fake_client.post_cross_domain_dismiss = AsyncMock(return_value=True)

    with patch("maxbot.handlers.cross_domain.get_nutrition_client",
               return_value=fake_client):
        await on_dismiss(event, ctx)

    assert fake_client.post_cross_domain_dismiss.await_count == 1
    call_kwargs = fake_client.post_cross_domain_dismiss.await_args.kwargs
    assert call_kwargs["shown_id"] == "abc-123"
    # Soft confirmation sent to user
    assert event.bot.send_message.await_count == 1


@pytest.mark.django_db(transaction=True)
async def test_convert_callback_redirects_to_booking_flow():
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.cross_domain import on_convert

    event = _make_callback(payload="cb:cross:convert:abc-123", user_id=30002)
    ctx = MemoryContext(chat_id=100, user_id=30002)

    fake_client = MagicMock()
    fake_client.post_cross_domain_convert = AsyncMock(return_value=True)
    fake_client.get_cross_domain_insights = AsyncMock(return_value=_make_insight())

    # Bot has no active appointment_id available — should redirect to booking
    with patch("maxbot.handlers.cross_domain.get_nutrition_client",
               return_value=fake_client), \
            patch("maxbot.handlers.cross_domain._send_booking_redirect",
                  AsyncMock()) as redirect_mock:
        await on_convert(event, ctx)

    # Redirect to booking flow happened with the insight's category slug.
    assert redirect_mock.await_count == 1
    redirect_kwargs = redirect_mock.await_args.kwargs
    assert redirect_kwargs["service_category_slug"] == "massage"
    # Fire-and-forget convert POST attempted
    assert fake_client.post_cross_domain_convert.await_count == 1


@pytest.mark.django_db(transaction=True)
async def test_seen_callback_posts_seen():
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.cross_domain import on_seen

    event = _make_callback(payload="cb:cross:seen:abc-123", user_id=30003)
    ctx = MemoryContext(chat_id=100, user_id=30003)

    fake_client = MagicMock()
    fake_client.post_cross_domain_seen = AsyncMock(return_value=True)

    with patch("maxbot.handlers.cross_domain.get_nutrition_client",
               return_value=fake_client):
        await on_seen(event, ctx)

    assert fake_client.post_cross_domain_seen.await_count == 1
    assert fake_client.post_cross_domain_seen.await_args.kwargs["shown_id"] == "abc-123"


# ─── food_scanner hook ──────────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
async def test_food_scanner_hook_skips_when_eating_disorder(settings):
    """eating_disorder=True in BotUser.health_flags (model field) → no GET call."""
    from model_bakery import baker
    from asgiref.sync import sync_to_async

    from maxbot.handlers.food_scanner import _maybe_send_cross_domain_card

    settings.CROSS_DOMAIN_ENABLED = True
    # B-1 review: health_flags is a model field, not nested in context.
    bot_user = await sync_to_async(baker.make)(
        "services_app.BotUser",
        max_user_id=70001,
        health_flags={"eating_disorder": True},
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()
    fake_client = MagicMock()
    fake_client.get_cross_domain_insights = AsyncMock()

    with patch("maxbot.handlers.food_scanner.get_nutrition_client",
               return_value=fake_client):
        await _maybe_send_cross_domain_card(
            bot=bot, chat_id=100, bot_user=bot_user,
        )

    fake_client.get_cross_domain_insights.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
async def test_food_scanner_hook_skips_when_flag_off(settings):
    """CROSS_DOMAIN_ENABLED=False → no GET call."""
    from model_bakery import baker
    from asgiref.sync import sync_to_async

    from maxbot.handlers.food_scanner import _maybe_send_cross_domain_card

    settings.CROSS_DOMAIN_ENABLED = False
    bot_user = await sync_to_async(baker.make)(
        "services_app.BotUser", max_user_id=70002, context={},
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()
    fake_client = MagicMock()
    fake_client.get_cross_domain_insights = AsyncMock()

    with patch("maxbot.handlers.food_scanner.get_nutrition_client",
               return_value=fake_client):
        await _maybe_send_cross_domain_card(
            bot=bot, chat_id=100, bot_user=bot_user,
        )

    fake_client.get_cross_domain_insights.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
async def test_food_scanner_hook_silently_swallows_errors(settings):
    """If GET raises NutritionUnavailableError, log_meal flow is not broken."""
    from model_bakery import baker
    from asgiref.sync import sync_to_async

    from maxbot.handlers.food_scanner import _maybe_send_cross_domain_card

    settings.CROSS_DOMAIN_ENABLED = True
    bot_user = await sync_to_async(baker.make)(
        "services_app.BotUser", max_user_id=70003, context={},
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()
    fake_client = MagicMock()
    fake_client.get_cross_domain_insights = AsyncMock(
        side_effect=NutritionUnavailableError("circuit_open"),
    )

    with patch("maxbot.handlers.food_scanner.get_nutrition_client",
               return_value=fake_client):
        # Must NOT raise.
        await _maybe_send_cross_domain_card(
            bot=bot, chat_id=100, bot_user=bot_user,
        )

    # No card was sent.
    bot.send_message.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
async def test_food_scanner_hook_sends_card_when_insight_available(settings):
    """Happy path: feature flag on, no eating_disorder, insight returned → card sent + seen POSTed."""
    from model_bakery import baker
    from asgiref.sync import sync_to_async

    from maxbot.handlers.food_scanner import _maybe_send_cross_domain_card

    settings.CROSS_DOMAIN_ENABLED = True
    bot_user = await sync_to_async(baker.make)(
        "services_app.BotUser", max_user_id=70004, context={},
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()
    fake_client = MagicMock()
    fake_client.get_cross_domain_insights = AsyncMock(return_value=_make_insight())
    fake_client.post_cross_domain_seen = AsyncMock(return_value=True)

    with patch("maxbot.handlers.food_scanner.get_nutrition_client",
               return_value=fake_client):
        await _maybe_send_cross_domain_card(
            bot=bot, chat_id=100, bot_user=bot_user,
        )

    assert bot.send_message.await_count == 1
    sent = bot.send_message.await_args.kwargs
    assert "дефицит" in sent["text"]
    # seen POST happened
    assert fake_client.post_cross_domain_seen.await_count == 1


# ─── Settings flag ────────────────────────────────────────────────────────


async def test_cross_domain_enabled_default_off():
    from django.conf import settings as dj_settings
    assert getattr(dj_settings, "CROSS_DOMAIN_ENABLED", None) is False


async def test_cross_domain_router_registered_between_food_scanner_and_ai():
    """Order matters — cb:cross:* must be matched before generic message_created."""
    from maxbot.handlers import get_routers
    from maxbot.handlers.ai_assistant import router as ai_assistant_router
    from maxbot.handlers.cross_domain import router as cross_domain_router
    from maxbot.handlers.food_scanner import router as food_scanner_router

    routers = get_routers()
    assert cross_domain_router in routers
    fs_idx = routers.index(food_scanner_router)
    cd_idx = routers.index(cross_domain_router)
    ai_idx = routers.index(ai_assistant_router)
    assert fs_idx < cd_idx < ai_idx
