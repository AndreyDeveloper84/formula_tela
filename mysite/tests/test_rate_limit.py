"""
Smoke-тесты, что django-ratelimit навешан на публичные booking API.

Каждый тест открывает собственный LocMemCache (через override_settings
контекст-менеджер) и чистит его перед работой, чтобы состояние лимитов
не протекало между тестами.
"""
import json

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse


def _locmem(name):
    return {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": f"ratelimit-tests-{name}",
        }
    }


@pytest.mark.django_db
def test_wizard_booking_rate_limit_blocks_after_5_posts():
    """6-й POST с одного IP за минуту должен отдать 429."""
    with override_settings(CACHES=_locmem("wizard-rl"), RATELIMIT_ENABLE=True):
        cache.clear()
        client = Client()
        url = reverse("website:api_wizard_booking")
        payload = json.dumps({
            "client_name": "Test",
            "client_phone": "+79271234567",
            "service_id": None,
            "comment": "",
        })

        statuses = []
        for _ in range(6):
            resp = client.post(url, data=payload, content_type="application/json")
            statuses.append(resp.status_code)

        assert 429 in statuses, f"Ожидался 429 в {statuses}"
        assert statuses[:5].count(429) == 0, f"Первые 5 не должны быть 429: {statuses}"


@pytest.mark.django_db
def test_get_staff_rate_limit_allows_30_then_blocks():
    """GET /api/booking/get_staff/ — лимит 30/m, 31-й должен дать 429."""
    with override_settings(CACHES=_locmem("staff-rl"), RATELIMIT_ENABLE=True):
        cache.clear()
        client = Client()
        url = reverse("website:api_get_staff")

        statuses = [client.get(url).status_code for _ in range(31)]

        assert statuses[-1] == 429, f"31-й запрос должен быть 429, получено {statuses[-1]}"


@pytest.mark.django_db
def test_wizard_booking_invalid_phone_rejected():
    """Мусорный телефон → 400, до YClients не доходит."""
    with override_settings(CACHES=_locmem("wizard-phone"), RATELIMIT_ENABLE=True):
        cache.clear()
        client = Client()
        url = reverse("website:api_wizard_booking")
        resp = client.post(
            url,
            data=json.dumps({
                "client_name": "Test",
                "client_phone": "abc",
                "service_id": None,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.json()
        err = body.get("error", "").lower()
        assert "телефон" in err or "формат" in err
