"""Phase 3 T03: NutritionClient water — add/undo/today.

Pattern matched to test_nutrition_client.py / test_nutrition_client_profile.py.
"""
from __future__ import annotations

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


def _err_envelope(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": "x"}})


# ─── add_water ──────────────────────────────────────────────────────────────


async def test_add_water_201_returns_water_entry_response():
    """POST 201 with full water-entry payload → WaterEntryResponse.

    Body keys follow Ayla actual shape: `today_total_water_ml` / `today_norm_water_ml`
    (DRF-301 / B22 — sister bug to PR #133's nested norms fix).
    """
    transport = httpx.MockTransport(
        lambda r: _ok_envelope(
            {
                "entry_id": "water-uuid-1",
                "ml": 250,
                "water_ml": 250,  # plain water → coefficient 1.0
                "kcal": 0,
                "milestone_text": None,
                "today_total_water_ml": 250,
                "today_norm_water_ml": 2000,
                "alcohol_recovery_hint": False,
            },
            status=201,
        )
    )
    client = _make_client(transport)
    try:
        resp = await client.add_water(external_user_id="bot:1", ml=250)
    finally:
        client._reset_httpx()

    assert resp.entry_id == "water-uuid-1"
    assert resp.ml == 250
    assert resp.water_ml == 250
    assert resp.kcal == 0
    assert resp.milestone_text is None
    assert resp.today_total_ml == 250
    assert resp.today_norm_ml == 2000
    assert resp.alcohol_recovery_hint is False


async def test_add_water_with_beverage_coffee_applies_coefficient():
    """Кофе coefficient 0.95 — Ayla возвращает water_ml меньше ml."""
    transport = httpx.MockTransport(
        lambda r: _ok_envelope(
            {
                "entry_id": "water-uuid-2", "ml": 200, "water_ml": 190,
                "kcal": 5, "milestone_text": None,
                "today_total_water_ml": 1190, "today_norm_water_ml": 2000,
                "alcohol_recovery_hint": False,
            },
            status=201,
        )
    )
    client = _make_client(transport)
    try:
        resp = await client.add_water(
            external_user_id="bot:1", ml=200, beverage_slug="coffee",
        )
    finally:
        client._reset_httpx()
    assert resp.water_ml == 190
    assert resp.kcal == 5


async def test_add_water_milestone_50pct():
    """1L при норме 2L — Ayla возвращает milestone_text."""
    transport = httpx.MockTransport(
        lambda r: _ok_envelope(
            {
                "entry_id": "water-uuid-3", "ml": 500, "water_ml": 500,
                "kcal": 0,
                "milestone_text": "Половина нормы — отлично! 💧",
                "today_total_water_ml": 1000, "today_norm_water_ml": 2000,
                "alcohol_recovery_hint": False,
            },
            status=201,
        )
    )
    client = _make_client(transport)
    try:
        resp = await client.add_water(external_user_id="bot:1", ml=500)
    finally:
        client._reset_httpx()
    assert resp.milestone_text == "Половина нормы — отлично! 💧"


async def test_add_water_alcohol_returns_recovery_hint():
    """Wine — Ayla возвращает alcohol_recovery_hint=True для UX-блока «выпей воды»."""
    transport = httpx.MockTransport(
        lambda r: _ok_envelope(
            {
                "entry_id": "water-uuid-4", "ml": 150, "water_ml": 0,
                "kcal": 130, "milestone_text": None,
                "today_total_water_ml": 1000, "today_norm_water_ml": 2000,
                "alcohol_recovery_hint": True,
            },
            status=201,
        )
    )
    client = _make_client(transport)
    try:
        resp = await client.add_water(
            external_user_id="bot:1", ml=150, beverage_slug="wine_red",
        )
    finally:
        client._reset_httpx()
    assert resp.alcohol_recovery_hint is True
    assert resp.water_ml == 0


async def test_add_water_forwards_idempotency_header():
    """X-Idempotency-Key должен передаваться чтобы Ayla не дублировал на retry."""
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode("utf-8")
        return _ok_envelope(
            {
                "entry_id": "water-uuid-x", "ml": 250, "water_ml": 250, "kcal": 0,
                "milestone_text": None,
                "today_total_water_ml": 250, "today_norm_water_ml": 2000,
                "alcohol_recovery_hint": False,
            },
            status=201,
        )

    client = _make_client(httpx.MockTransport(_handler))
    try:
        await client.add_water(
            external_user_id="bot:7",
            ml=250,
            idempotency_key="ik-water-2026-05-03-1",
        )
    finally:
        client._reset_httpx()

    assert captured["headers"].get("x-idempotency-key") == "ik-water-2026-05-03-1"
    assert captured["headers"].get("x-external-user-id") == "bot:7"


async def test_add_water_forwards_ts_when_provided():
    """Optional `ts` (back-fill) передаётся в body."""
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured["body"] = _json.loads(request.content.decode("utf-8"))
        return _ok_envelope(
            {
                "entry_id": "x", "ml": 250, "water_ml": 250, "kcal": 0,
                "milestone_text": None,
                "today_total_water_ml": 250, "today_norm_water_ml": 2000,
                "alcohol_recovery_hint": False,
            },
            status=201,
        )

    client = _make_client(httpx.MockTransport(_handler))
    try:
        await client.add_water(
            external_user_id="bot:1", ml=250, ts="2026-05-03T08:30:00Z",
        )
    finally:
        client._reset_httpx()

    assert captured["body"].get("ts") == "2026-05-03T08:30:00Z"
    assert captured["body"].get("ml") == 250


async def test_add_water_5xx_raises_unavailable():
    transport = httpx.MockTransport(lambda r: httpx.Response(503, json={}))
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionUnavailableError):
            await client.add_water(external_user_id="bot:1", ml=250)
    finally:
        client._reset_httpx()


async def test_add_water_400_invalid_beverage_raises_api_error():
    transport = httpx.MockTransport(lambda r: _err_envelope(400, "INVALID_BEVERAGE"))
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionAPIError):
            await client.add_water(
                external_user_id="bot:1", ml=250, beverage_slug="liquid_nitrogen",
            )
    finally:
        client._reset_httpx()


# ─── undo_water (soft-delete) ───────────────────────────────────────────────


async def test_undo_water_204_returns_true():
    """DELETE /water/{entry_id}/ → 204 No Content → True."""
    transport = httpx.MockTransport(lambda r: httpx.Response(204))
    client = _make_client(transport)
    try:
        ok = await client.undo_water(external_user_id="bot:1", entry_id="water-uuid-1")
    finally:
        client._reset_httpx()
    assert ok is True


async def test_undo_water_uses_correct_url():
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(204)

    client = _make_client(httpx.MockTransport(_handler))
    try:
        await client.undo_water(external_user_id="bot:9", entry_id="water-abc-123")
    finally:
        client._reset_httpx()

    assert captured["method"] == "DELETE"
    assert captured["url"].endswith("/api/v1/nutrition/internal/water/water-abc-123/")
    assert captured["headers"].get("x-external-user-id") == "bot:9"


async def test_undo_water_404_returns_false():
    """404 — restore window истёк или entry уже удалён → False, не ошибка."""
    transport = httpx.MockTransport(lambda r: _err_envelope(404, "ENTRY_NOT_FOUND"))
    client = _make_client(transport)
    try:
        ok = await client.undo_water(external_user_id="bot:1", entry_id="water-x")
    finally:
        client._reset_httpx()
    assert ok is False


async def test_undo_water_5xx_raises_unavailable():
    transport = httpx.MockTransport(lambda r: httpx.Response(503, json={}))
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionUnavailableError):
            await client.undo_water(external_user_id="bot:1", entry_id="x")
    finally:
        client._reset_httpx()


# ─── get_water_today ────────────────────────────────────────────────────────


async def test_get_water_today_returns_entries_and_totals():
    """GET /water/today/ → WaterTodayResponse {entries, total_ml, norm_ml}.

    Body keys follow Ayla actual shape: `today_total_water_ml` / `today_norm_water_ml`
    (DRF-301 / B22).
    """
    transport = httpx.MockTransport(
        lambda r: _ok_envelope({
            "today_total_water_ml": 1500,
            "today_norm_water_ml": 2000,
            "entries": [
                {"entry_id": "e1", "ml": 500, "water_ml": 500, "ts": "2026-05-03T08:00:00Z"},
                {"entry_id": "e2", "ml": 200, "water_ml": 190, "ts": "2026-05-03T10:30:00Z",
                 "beverage_slug": "coffee"},
                {"entry_id": "e3", "ml": 800, "water_ml": 800, "ts": "2026-05-03T14:00:00Z"},
            ],
        })
    )
    client = _make_client(transport)
    try:
        resp = await client.get_water_today(external_user_id="bot:1")
    finally:
        client._reset_httpx()

    assert resp.total_ml == 1500
    assert resp.norm_ml == 2000
    assert len(resp.entries) == 3
    assert resp.entries[0]["entry_id"] == "e1"
    assert resp.entries[1]["beverage_slug"] == "coffee"


async def test_get_water_today_empty_day():
    """Пустой день — entries=[], total_ml=0, norm_ml > 0 (есть профиль)."""
    transport = httpx.MockTransport(
        lambda r: _ok_envelope(
            {"today_total_water_ml": 0, "today_norm_water_ml": 2000, "entries": []}
        )
    )
    client = _make_client(transport)
    try:
        resp = await client.get_water_today(external_user_id="bot:1")
    finally:
        client._reset_httpx()
    assert resp.total_ml == 0
    assert resp.norm_ml == 2000
    assert resp.entries == []


async def test_get_water_today_5xx_raises_unavailable():
    transport = httpx.MockTransport(lambda r: httpx.Response(502, json={}))
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionUnavailableError):
            await client.get_water_today(external_user_id="bot:1")
    finally:
        client._reset_httpx()


async def test_get_water_today_reads_actual_ayla_shape():
    """B22 regression: GET /water/today/ parses actual Ayla envelope keys.

    Live evidence (2026-05-07, bot:66368800):
        {
          "today_total_water_ml": 0,
          "today_norm_water_ml": 2000,
          "today_kcal_from_beverages": 0.0,
          "today_caffeine_mg": 0.0,
          "today_total_coffee_cups": 0,
          "today_total_tea_cups": 0,
          ...
        }

    Ensures all 6 fields populate correctly on WaterTodayResponse.
    """
    transport = httpx.MockTransport(
        lambda r: _ok_envelope({
            "date": "2026-05-07",
            "entries": [],
            "today_total_water_ml": 1500,
            "today_norm_water_ml": 2000,
            "today_kcal_from_beverages": 120.5,
            "today_caffeine_mg": 85.0,
            "today_total_coffee_cups": 2,
            "today_total_tea_cups": 1,
        })
    )
    client = _make_client(transport)
    try:
        resp = await client.get_water_today(external_user_id="bot:66368800")
    finally:
        client._reset_httpx()

    # Backward-compat fields (Ayla key → DTO field rename)
    assert resp.total_ml == 1500
    assert resp.norm_ml == 2000
    # New fields exposed for daily report + caffeine warnings
    assert resp.kcal_from_beverages == 120.5
    assert resp.caffeine_mg == 85.0
    assert resp.coffee_cups == 2
    assert resp.tea_cups == 1
