"""
Contract-тесты для booking/wizard API endpoints.

Проверяют что ответ содержит **ровно** ожидаемый набор ключей — не меньше
и не больше. Ловят случайный field leak: добавили поле в `Service` →
JSON-эндпоинт случайно начал его возвращать.

Существующие тесты в `test_api_views.py` проверяют что нужные ключи
ЕСТЬ (`assert "id" in data["data"][0]`); эти тесты дополнительно ловят
ЛИШНИЕ ключи через `set(...) == set(...)` сравнение.
"""
import json
import pytest
from unittest.mock import patch


def _yclients_patch(mock_api):
    return patch("services_app.yclients_api.get_yclients_api", return_value=mock_api)


# ─── api_wizard_categories ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_wizard_categories_response_keys(client, category, service):
    """Ответ envelope содержит только `categories`; элементы — ровно 3 поля."""
    resp = client.get("/api/wizard/categories/")
    body = resp.json()
    assert set(body.keys()) == {"categories"}
    assert body["categories"], "категория с активной услугой должна попасть в ответ"
    item = body["categories"][0]
    assert set(item.keys()) == {"id", "name", "services_count"}


# ─── api_wizard_services ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_wizard_services_response_keys(client, category, service, service_option):
    """Ответ envelope содержит только `services`; элементы — ровно 5 полей."""
    resp = client.get(f"/api/wizard/categories/{category.id}/services/")
    body = resp.json()
    assert set(body.keys()) == {"services"}
    assert body["services"]
    item = body["services"][0]
    assert set(item.keys()) == {"id", "name", "duration", "price", "option_id"}


# ─── api_service_options ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_service_options_response_keys(client, service, service_option):
    """Envelope: success/data/service_name. Элемент data — ровно 7 полей."""
    resp = client.get(f"/api/booking/service_options/?service_id={service.id}")
    body = resp.json()
    assert set(body.keys()) == {"success", "data", "service_name"}
    assert body["data"]
    item = body["data"][0]
    assert set(item.keys()) == {
        "id", "duration", "quantity", "unit_type",
        "unit_type_display", "price", "yclients_id",
    }


# ─── api_get_staff ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_staff_response_keys(client, service_option, mock_yclients_api):
    """Envelope: success/data/count. Элемент data — ровно 5 полей мастера."""
    with _yclients_patch(mock_yclients_api):
        resp = client.get(f"/api/booking/get_staff/?service_option_id={service_option.id}")
    body = resp.json()
    assert set(body.keys()) == {"success", "data", "count"}
    assert body["data"]
    item = body["data"][0]
    assert set(item.keys()) == {"id", "name", "specialization", "avatar", "rating"}


@pytest.mark.django_db
def test_get_staff_all_staff_response_keys(client, mock_yclients_api):
    """Ветка ?all_staff=1 — те же ключи мастера."""
    with _yclients_patch(mock_yclients_api):
        resp = client.get("/api/booking/get_staff/?all_staff=1")
    body = resp.json()
    assert set(body.keys()) == {"success", "data", "count"}
    item = body["data"][0]
    assert set(item.keys()) == {"id", "name", "specialization", "avatar", "rating"}


# ─── api_create_booking ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_booking_response_keys(client, mock_yclients_api):
    """Envelope: success/data. Элемент data — ровно 8 полей бронирования."""
    mock_yclients_api.create_booking.return_value = {
        "record_id": 12345,
        "record_hash": "abc123hash",
    }
    payload = {
        "staff_id": 1,
        "service_ids": [10000001],
        "date": "2026-12-15",
        "time": "10:00",
        "client": {
            "name": "Иван Петров",
            "phone": "+79001234567",
        },
        "comment": "тест",
    }
    with _yclients_patch(mock_yclients_api):
        resp = client.post(
            "/api/booking/create/",
            data=json.dumps(payload),
            content_type="application/json",
        )
    body = resp.json()
    assert resp.status_code == 200, body
    assert set(body.keys()) == {"success", "data"}
    data = body["data"]
    assert set(data.keys()) == {
        "booking_id", "booking_hash", "staff_id", "staff_name",
        "datetime", "service_ids", "client_name", "comment",
    }
    # Sanity: значения сошлись.
    assert data["booking_id"] == 12345
    assert data["staff_id"] == 1
    assert data["service_ids"] == [10000001]
    assert data["client_name"] == "Иван Петров"
