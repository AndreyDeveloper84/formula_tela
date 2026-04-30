"""DRF-246: NutritionClient — httpx-based service-to-service client."""
from __future__ import annotations

import time

import httpx
import pytest

from maxbot.services.nutrition_client import (
    CIRCUIT_FAILURE_THRESHOLD,
    FoodNotRecognizedError,
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
    # Monkey-patch httpx.AsyncClient to use our transport.
    original = httpx.AsyncClient

    class _PatchedClient(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    # Replace globally for the duration of one call — pytest fixtures
    # would be cleaner but this keeps the helper local.
    httpx.AsyncClient = _PatchedClient  # type: ignore[misc]
    client._reset_httpx = lambda: setattr(httpx, "AsyncClient", original)
    return client


def _ok_envelope(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"data": data})


def _err_envelope(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": "x"}})


async def test_scan_success_parses_envelope():
    transport = httpx.MockTransport(
        lambda r: _ok_envelope({
            "id": "scan-uuid",
            "dish_name": "Борщ",
            "confidence": 0.92,
            "portion_g": 300,
            "nutrition": {"calories": 250, "protein_g": 8},
            "provider": "openai",
        })
    )
    client = _make_client(transport)
    try:
        resp = await client.scan_photo(
            external_user_id="bot:1",
            image_bytes=b"\xff\xd8\xff",
        )
    finally:
        client._reset_httpx()

    assert resp.scan_id == "scan-uuid"
    assert resp.dish_name == "Борщ"
    assert resp.confidence == 0.92
    assert resp.nutrition == {"calories": 250, "protein_g": 8}
    assert resp.provider == "openai"


async def test_scan_400_food_not_recognized_raises():
    transport = httpx.MockTransport(
        lambda r: _err_envelope(400, "FOOD_NOT_RECOGNIZED")
    )
    client = _make_client(transport)
    try:
        with pytest.raises(FoodNotRecognizedError):
            await client.scan_photo(external_user_id="bot:1", image_bytes=b"x")
    finally:
        client._reset_httpx()


async def test_scan_503_food_api_unavailable_raises_unavailable():
    transport = httpx.MockTransport(
        lambda r: _err_envelope(503, "FOOD_API_UNAVAILABLE")
    )
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionUnavailableError):
            await client.scan_photo(external_user_id="bot:1", image_bytes=b"x")
    finally:
        client._reset_httpx()


async def test_scan_5xx_records_failure_and_opens_circuit():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(500, text="boom")
    )
    client = _make_client(transport)
    try:
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            with pytest.raises(NutritionUnavailableError):
                await client.scan_photo(external_user_id="bot:1", image_bytes=b"x")

        # Next call must short-circuit, not reach the transport.
        with pytest.raises(NutritionUnavailableError) as exc:
            await client.scan_photo(external_user_id="bot:1", image_bytes=b"x")
        assert "circuit_open" in str(exc.value)
    finally:
        client._reset_httpx()


async def test_scan_validates_required_settings():
    with pytest.raises(ValueError):
        NutritionClient(base_url="", service_token="x")
    with pytest.raises(ValueError):
        NutritionClient(base_url="http://ayla", service_token="")


async def test_scan_unknown_4xx_raises_generic_api_error():
    transport = httpx.MockTransport(
        lambda r: _err_envelope(400, "VALIDATION_ERROR")
    )
    client = _make_client(transport)
    try:
        with pytest.raises(NutritionAPIError) as exc:
            await client.scan_photo(external_user_id="bot:1", image_bytes=b"x")
        # Distinguishes from FoodNotRecognizedError / NutritionUnavailableError.
        assert not isinstance(exc.value, FoodNotRecognizedError)
        assert not isinstance(exc.value, NutritionUnavailableError)
    finally:
        client._reset_httpx()


async def test_request_carries_service_token_and_external_id():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("X-Service-Token", "")
        seen["external_id"] = request.headers.get("X-External-User-ID", "")
        return _ok_envelope({
            "id": "x", "dish_name": "X", "confidence": 0.5,
            "portion_g": 100, "nutrition": None, "provider": "openai",
        })

    client = _make_client(httpx.MockTransport(handler))
    try:
        await client.scan_photo(external_user_id="bot:42", image_bytes=b"x")
    finally:
        client._reset_httpx()

    assert seen["token"] == "test-token"
    assert seen["external_id"] == "bot:42"
