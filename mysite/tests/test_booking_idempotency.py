"""
Тесты idempotency-кэша в booking API.

Проверяем 3 endpoints: api_wizard_booking, api_bundle_request,
api_create_booking. Каждый тест использует свой LocMem cache, чтобы
состояние не протекало между тестами.
"""
import json
from unittest.mock import patch, MagicMock

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse


def _locmem(name):
    return {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": f"idempotency-tests-{name}",
        }
    }


# ──────────────────── api_wizard_booking ────────────────────

@pytest.mark.django_db
def test_wizard_booking_double_submit_does_not_create_duplicate(mock_telegram):
    """Два одинаковых POST подряд → в БД одна запись, второй раз отдаётся кэш."""
    from services_app.models import BookingRequest

    with override_settings(CACHES=_locmem("wizard-dup")):
        cache.clear()
        client = Client()
        url = reverse("website:api_wizard_booking")
        payload = json.dumps({
            "client_name": "Анна",
            "client_phone": "+79271234567",
            "service_id": None,
            "comment": "тест",
        })

        r1 = client.post(url, data=payload, content_type="application/json")
        r2 = client.post(url, data=payload, content_type="application/json")

        assert r1.status_code == 200
        assert r2.status_code == 200
        # BookingRequest создан ровно один раз
        assert BookingRequest.objects.count() == 1
        # Оба ответа содержат тот же id (второй — из кэша)
        assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.django_db
def test_wizard_booking_different_phone_creates_two(mock_telegram):
    """Разные клиенты на тот же service_id — два BookingRequest."""
    from services_app.models import BookingRequest

    with override_settings(CACHES=_locmem("wizard-diff")):
        cache.clear()
        client = Client()
        url = reverse("website:api_wizard_booking")

        client.post(
            url,
            data=json.dumps({
                "client_name": "A",
                "client_phone": "+79271111111",
                "service_id": None,
                "comment": "x",
            }),
            content_type="application/json",
        )
        client.post(
            url,
            data=json.dumps({
                "client_name": "B",
                "client_phone": "+79272222222",
                "service_id": None,
                "comment": "x",
            }),
            content_type="application/json",
        )

        assert BookingRequest.objects.count() == 2


# ──────────────────── api_bundle_request ────────────────────

@pytest.mark.django_db
def test_bundle_request_double_submit_does_not_duplicate(mock_telegram):
    """Дубль заявки на пакет возвращает кэш и не создаёт вторую BundleRequest."""
    from services_app.models import BundleRequest

    with override_settings(CACHES=_locmem("bundle-dup")):
        cache.clear()
        client = Client()
        url = reverse("website:api_bundle_request")
        payload = json.dumps({
            "name": "Ольга",
            "phone": "+79273334455",
            "email": "",
            "comment": "SPA для двоих",
            "bundle_id": None,
            "bundle_name": "SPA Deluxe",
        })

        r1 = client.post(url, data=payload, content_type="application/json")
        r2 = client.post(url, data=payload, content_type="application/json")

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert BundleRequest.objects.count() == 1


# ──────────────────── api_create_booking ────────────────────

@pytest.mark.django_db
def test_create_booking_double_submit_calls_yclients_once():
    """Двойной POST на YClients → create_booking вызван 1 раз."""
    with override_settings(CACHES=_locmem("create-dup")):
        cache.clear()

        fake_api = MagicMock()
        fake_api.get_staff.return_value = [{"id": 4416525, "name": "Анна"}]
        fake_api.create_booking.return_value = {
            "record_id": 12345,
            "record_hash": "abc",
        }

        with patch("services_app.yclients_api.get_yclients_api", return_value=fake_api):
            client = Client()
            url = reverse("website:api_create_booking")
            payload = json.dumps({
                "staff_id": 4416525,
                "service_ids": [10461107],
                "date": "2026-05-15",
                "time": "10:00",
                "client": {"name": "Иван", "phone": "+79271234567"},
                "comment": "тест",
            })

            r1 = client.post(url, data=payload, content_type="application/json")
            r2 = client.post(url, data=payload, content_type="application/json")

            assert r1.status_code == 200, r1.content
            assert r2.status_code == 200
            # YClients API дёрнули ровно один раз
            assert fake_api.create_booking.call_count == 1
            # Оба клиентских ответа идентичны
            assert r1.json() == r2.json()


@pytest.mark.django_db
def test_create_booking_yclients_error_not_cached():
    """Ошибка YClients НЕ кэшируется — повтор идёт в API заново."""
    from services_app.yclients_api import YClientsAPIError

    with override_settings(CACHES=_locmem("create-err")):
        cache.clear()

        fake_api = MagicMock()
        fake_api.get_staff.return_value = [{"id": 4416525, "name": "Анна"}]
        # Первый вызов — падаем, второй — успех
        fake_api.create_booking.side_effect = [
            YClientsAPIError("boom"),
            {"record_id": 99, "record_hash": "ok"},
        ]

        with patch("services_app.yclients_api.get_yclients_api", return_value=fake_api):
            client = Client()
            url = reverse("website:api_create_booking")
            payload = json.dumps({
                "staff_id": 4416525,
                "service_ids": [10461107],
                "date": "2026-05-15",
                "time": "10:00",
                "client": {"name": "Иван", "phone": "+79271234567"},
                "comment": "",
            })

            r1 = client.post(url, data=payload, content_type="application/json")
            r2 = client.post(url, data=payload, content_type="application/json")

            assert r1.status_code == 500
            assert r2.status_code == 200
            assert fake_api.create_booking.call_count == 2
