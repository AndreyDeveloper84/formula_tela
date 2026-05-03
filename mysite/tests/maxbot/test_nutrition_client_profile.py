"""Phase 3 T03: NutritionClient profile + water methods.

Pattern matched to existing test_nutrition_client.py:
- httpx.MockTransport injected via _make_client helper
- Envelope parsers _ok_envelope / _err_envelope
- pytestmark = pytest.mark.asyncio
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
    """Same pattern as test_nutrition_client.py — patch httpx.AsyncClient globally."""
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


def _ok_envelope(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"data": data})


def _err_envelope(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": "x"}})


# ─── get_profile ────────────────────────────────────────────────────────────


async def test_get_profile_success_returns_profile_response():
    """200 with full profile data → ProfileResponse populated."""
    transport = httpx.MockTransport(
        lambda r: _ok_envelope({
            "gender": "female",
            "age": 32,
            "height_cm": 168,
            "weight_kg": 65,
            "goal": "tone",
            "goal_pace": "balanced",
            "activity": "moderate",
            "health_flags": {"pregnant": False, "eating_disorder": False},
            "diet_preference": "any",
            "disclaimer_acked": {"ts": "2026-05-03T10:00:00Z", "version": 1},
            "daily_kcal": 1850,
            "protein_g": 90,
            "fat_g": 60,
            "carbs_g": 220,
            "water_ml": 2000,
            "bmr": 1450,
            "goal_overridden_by": None,
        })
    )
    client = _make_client(transport)
    try:
        resp = await client.get_profile(external_user_id="bot:1")
    finally:
        client._reset_httpx()

    assert resp is not None
    assert resp.gender == "female"
    assert resp.age == 32
    assert resp.height_cm == 168
    assert resp.weight_kg == 65
    assert resp.goal == "tone"
    assert resp.daily_kcal == 1850
    assert resp.water_ml == 2000
    assert resp.bmr == 1450
    assert resp.health_flags == {"pregnant": False, "eating_disorder": False}
    assert resp.disclaimer_acked == {"ts": "2026-05-03T10:00:00Z", "version": 1}
    assert resp.goal_overridden_by is None


async def test_get_profile_404_returns_none():
    """404 PROFILE_NOT_FOUND → None (caller знает что анкеты ещё не было)."""
    transport = httpx.MockTransport(lambda r: _err_envelope(404, "PROFILE_NOT_FOUND"))
    client = _make_client(transport)
    try:
        resp = await client.get_profile(external_user_id="bot:1")
    finally:
        client._reset_httpx()
    assert resp is None


async def test_get_profile_5xx_raises_unavailable():
    """5xx → circuit failure + NutritionUnavailableError (как scan/log/summary)."""
    transport = httpx.MockTransport(lambda r: httpx.Response(503, json={}))
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionUnavailableError):
            await client.get_profile(external_user_id="bot:1")
    finally:
        client._reset_httpx()


async def test_get_profile_sends_service_token_and_external_id():
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["url"] = str(request.url)
        return _ok_envelope({
            "gender": "male", "age": 30, "height_cm": 180, "weight_kg": 80,
            "goal": "maintain", "daily_kcal": 2400, "protein_g": 120,
            "fat_g": 80, "carbs_g": 280, "water_ml": 2500, "bmr": 1800,
            "health_flags": {}, "disclaimer_acked": None,
        })

    client = _make_client(httpx.MockTransport(_handler))
    try:
        await client.get_profile(external_user_id="bot:42")
    finally:
        client._reset_httpx()

    assert captured["headers"].get("x-service-token") == "test-token"
    assert captured["headers"].get("x-external-user-id") == "bot:42"
    assert "/api/v1/nutrition/internal/profile/" in captured["url"]


async def test_get_profile_other_4xx_raises_api_error():
    """403 / 401 / non-404 4xx → NutritionAPIError (caller logs + ретрай не имеет смысла)."""
    transport = httpx.MockTransport(lambda r: _err_envelope(403, "FORBIDDEN"))
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionAPIError):
            await client.get_profile(external_user_id="bot:1")
    finally:
        client._reset_httpx()


# ─── upsert_profile ─────────────────────────────────────────────────────────


async def test_upsert_profile_201_returns_profile_with_calculated_norms():
    """POST с заполненной анкетой → 201 и Ayla возвращает рассчитанные нормы."""
    transport = httpx.MockTransport(
        lambda r: httpx.Response(201, json={"data": {
            "gender": "female", "age": 32, "height_cm": 168, "weight_kg": 65,
            "goal": "lose", "goal_pace": "slow", "activity": "moderate",
            "daily_kcal": 1650, "protein_g": 100, "fat_g": 55, "carbs_g": 180,
            "water_ml": 2000, "bmr": 1450,
            "health_flags": {"pregnant": False},
            "disclaimer_acked": {"ts": "2026-05-03T10:00:00Z", "version": 1},
            "goal_overridden_by": None,
        }})
    )
    client = _make_client(transport)
    try:
        resp = await client.upsert_profile(
            external_user_id="bot:1",
            data={
                "gender": "female", "age": 32, "height_cm": 168, "weight_kg": 65,
                "goal": "lose", "goal_pace": "slow",
            },
        )
    finally:
        client._reset_httpx()

    assert resp.gender == "female"
    assert resp.daily_kcal == 1650
    assert resp.bmr == 1450
    assert resp.goal_overridden_by is None


async def test_upsert_profile_200_on_update():
    """200 (вместо 201) — Ayla обновила существующий профиль."""
    transport = httpx.MockTransport(
        lambda r: _ok_envelope({
            "gender": "female", "age": 32, "height_cm": 168, "weight_kg": 60,
            "goal": "lose", "daily_kcal": 1500, "protein_g": 90, "fat_g": 50,
            "carbs_g": 170, "water_ml": 1900, "bmr": 1380,
            "health_flags": {}, "disclaimer_acked": None,
        })
    )
    client = _make_client(transport)
    try:
        resp = await client.upsert_profile(external_user_id="bot:1", data={"weight_kg": 60})
    finally:
        client._reset_httpx()
    assert resp.weight_kg == 60


async def test_upsert_profile_pregnancy_overrides_goal():
    """Phase 2.4 health screening: Ayla сообщает goal_overridden_by на финале."""
    transport = httpx.MockTransport(
        lambda r: httpx.Response(201, json={"data": {
            "gender": "female", "age": 30, "height_cm": 165, "weight_kg": 70,
            "goal": "maintain",  # бот отправил "lose", Ayla переопределила
            "daily_kcal": 2200, "protein_g": 100, "fat_g": 70, "carbs_g": 250,
            "water_ml": 2200, "bmr": 1500,
            "health_flags": {"pregnant": True}, "disclaimer_acked": None,
            "goal_overridden_by": "pregnancy",
        }})
    )
    client = _make_client(transport)
    try:
        resp = await client.upsert_profile(
            external_user_id="bot:1",
            data={"goal": "lose", "health_flags": {"pregnant": True}},
        )
    finally:
        client._reset_httpx()
    assert resp.goal == "maintain"
    assert resp.goal_overridden_by == "pregnancy"


async def test_upsert_profile_sends_data_as_json_body():
    """POST body содержит data как JSON (не form-encoded)."""
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured["body"] = _json.loads(request.content.decode("utf-8"))
        captured["headers"] = dict(request.headers)
        return _ok_envelope({
            "gender": "male", "age": 28, "height_cm": 175, "weight_kg": 70,
            "goal": "maintain", "daily_kcal": 2200, "protein_g": 110,
            "fat_g": 75, "carbs_g": 260, "water_ml": 2300, "bmr": 1600,
            "health_flags": {}, "disclaimer_acked": None,
        })

    client = _make_client(httpx.MockTransport(_handler))
    try:
        await client.upsert_profile(
            external_user_id="bot:55",
            data={"gender": "male", "age": 28, "height_cm": 175, "weight_kg": 70},
        )
    finally:
        client._reset_httpx()

    assert captured["body"] == {"gender": "male", "age": 28, "height_cm": 175, "weight_kg": 70}
    assert captured["headers"].get("x-external-user-id") == "bot:55"


async def test_upsert_profile_5xx_raises_unavailable():
    transport = httpx.MockTransport(lambda r: httpx.Response(502, json={}))
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionUnavailableError):
            await client.upsert_profile(external_user_id="bot:1", data={"gender": "female"})
    finally:
        client._reset_httpx()


async def test_upsert_profile_validation_4xx_raises_api_error():
    """400 VALIDATION_ERROR (например age=200) → NutritionAPIError."""
    transport = httpx.MockTransport(lambda r: _err_envelope(400, "VALIDATION_ERROR"))
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionAPIError):
            await client.upsert_profile(external_user_id="bot:1", data={"age": 200})
    finally:
        client._reset_httpx()
