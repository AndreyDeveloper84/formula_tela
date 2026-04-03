"""
Тесты JSON API-эндпоинтов. YClients и Telegram замоканы.
"""
import json
import pytest
from unittest.mock import patch
from model_bakery import baker


def _yclients_patch(mock_api):
    """
    Патч get_yclients_api на уровне модуля services_app.yclients_api.
    Вьюхи делают локальный импорт внутри функции, поэтому патчим источник.
    """
    return patch("services_app.yclients_api.get_yclients_api", return_value=mock_api)


# ─── api_get_staff ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_get_staff_without_option_id(client):
    """Без service_option_id → 200, пустой список (нет yclients_service_id)."""
    resp = client.get("/api/booking/get_staff/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"] == []


@pytest.mark.django_db
def test_api_get_staff_with_valid_option(client, service_option, mock_yclients_api):
    """С валидным service_option_id → список мастеров из YClients."""
    with _yclients_patch(mock_yclients_api):
        resp = client.get(f"/api/booking/get_staff/?service_option_id={service_option.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) >= 1
    assert "id" in data["data"][0]
    assert "name" in data["data"][0]


@pytest.mark.django_db
def test_api_get_staff_no_yclients_id(client, service_option):
    """ServiceOption без yclients_service_id → пустой список."""
    service_option.yclients_service_id = ""
    service_option.save()
    resp = client.get(f"/api/booking/get_staff/?service_option_id={service_option.id}")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.django_db
def test_api_get_staff_invalid_option_id(client):
    resp = client.get("/api/booking/get_staff/?service_option_id=99999")
    assert resp.status_code == 404


# ─── api_available_dates ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_available_dates_no_staff_id(client):
    resp = client.get("/api/booking/available_dates/")
    assert resp.status_code == 400
    assert resp.json()["success"] is False


@pytest.mark.django_db
def test_api_available_dates_with_staff_id(client, mock_yclients_api):
    with _yclients_patch(mock_yclients_api):
        resp = client.get("/api/booking/available_dates/?staff_id=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "dates" in data["data"]
    assert isinstance(data["data"]["dates"], list)


@pytest.mark.django_db
def test_api_available_dates_yclients_error(client):
    """YClientsAPIError из get_yclients_api() → 500 с success=False."""
    from services_app.yclients_api import YClientsAPIError
    with patch("services_app.yclients_api.get_yclients_api", side_effect=YClientsAPIError("недоступно")):
        resp = client.get("/api/booking/available_dates/?staff_id=1")
    assert resp.status_code == 500
    assert resp.json()["success"] is False


# ─── api_available_times ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_available_times_missing_params(client):
    resp = client.get("/api/booking/available_times/")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_api_available_times_valid(client, mock_yclients_api):
    with _yclients_patch(mock_yclients_api):
        resp = client.get("/api/booking/available_times/?staff_id=1&date=2026-03-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "times" in data["data"]


# ─── api_service_options ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_service_options_no_service_id(client):
    resp = client.get("/api/booking/service_options/")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_api_service_options_invalid_service(client):
    resp = client.get("/api/booking/service_options/?service_id=99999")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_api_service_options_valid(client, service, service_option):
    resp = client.get(f"/api/booking/service_options/?service_id={service.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    opt = data["data"][0]
    assert opt["id"] == service_option.id
    assert opt["duration"] == service_option.duration_min
    assert float(opt["price"]) == float(service_option.price)


# ─── api_wizard_categories ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_wizard_categories_empty(client):
    resp = client.get("/api/wizard/categories/")
    assert resp.status_code == 200
    assert resp.json()["categories"] == []


@pytest.mark.django_db
def test_api_wizard_categories_with_active_services(client, category, service):
    resp = client.get("/api/wizard/categories/")
    ids = [c["id"] for c in resp.json()["categories"]]
    assert category.id in ids


@pytest.mark.django_db
def test_api_wizard_categories_excludes_empty(client):
    """Категория без активных услуг не попадает в ответ."""
    empty_cat = baker.make("services_app.ServiceCategory", name="Пустая")
    resp = client.get("/api/wizard/categories/")
    ids = [c["id"] for c in resp.json()["categories"]]
    assert empty_cat.id not in ids


# ─── api_wizard_services ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_wizard_services_returns_services(client, category, service):
    resp = client.get(f"/api/wizard/categories/{category.id}/services/")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()["services"]]
    assert service.name in names


@pytest.mark.django_db
def test_api_wizard_services_empty_category(client, category):
    """Нет активных услуг → пустой список."""
    resp = client.get(f"/api/wizard/categories/{category.id}/services/")
    assert resp.json()["services"] == []


# ─── api_wizard_booking ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_wizard_booking_creates_booking_request(client, service, mock_telegram):
    payload = {
        "client_name": "Иван Петров",
        "client_phone": "+79001234567",
        "service_id": service.id,
        "comment": "",
    }
    resp = client.post(
        "/api/wizard/booking/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    from services_app.models import BookingRequest
    assert BookingRequest.objects.filter(service_name=service.name).exists()


@pytest.mark.django_db
def test_api_wizard_booking_missing_fields(client):
    """Отсутствие обязательных полей → 400."""
    resp = client.post(
        "/api/wizard/booking/",
        data=json.dumps({"client_name": "Иван"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_api_wizard_booking_invalid_json(client):
    resp = client.post(
        "/api/wizard/booking/",
        data="not-json",
        content_type="application/json",
    )
    assert resp.status_code == 400


# ─── api_bundle_request ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_bundle_request_creates_record(client, bundle, mock_telegram):
    payload = {
        "name": "Анна Сидорова",
        "phone": "+79001112233",
        "bundle_id": bundle.id,
        "bundle_name": bundle.name,
    }
    resp = client.post(
        "/api/bundle/request/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    from services_app.models import BundleRequest
    assert BundleRequest.objects.filter(client_name="Анна Сидорова").exists()


@pytest.mark.django_db
def test_api_bundle_request_missing_name_phone(client):
    resp = client.post(
        "/api/bundle/request/",
        data=json.dumps({"bundle_name": "Комплекс"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_api_bundle_request_nonexistent_bundle(client, mock_telegram):
    """Несуществующий bundle_id → 200, bundle=None в записи."""
    payload = {
        "name": "Тест",
        "phone": "+70000000000",
        "bundle_id": 99999,
        "bundle_name": "Несуществующий",
    }
    resp = client.post(
        "/api/bundle/request/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    from services_app.models import BundleRequest
    req = BundleRequest.objects.filter(client_name="Тест").first()
    assert req is not None
    assert req.bundle is None
