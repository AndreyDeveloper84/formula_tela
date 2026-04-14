"""
Общие фикстуры для всех тестов.
"""
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from django.conf import settings
from model_bakery import baker


# ── Кэш в тестах: LocMem вместо Redis, ratelimit по умолчанию выключен ────
# В проде CACHES указывает на Redis, которого в CI/локальном pytest может не
# быть. django-ratelimit использует default cache, поэтому без этой правки
# любые booking-тесты падают на redis.ConnectionError. RATELIMIT_ENABLE=False
# глобально отключает лимиты — отдельные тесты, которые хотят проверить
# лимит, включают его через @override_settings.
settings.CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pytest-default-cache",
    }
}
settings.RATELIMIT_ENABLE = False


# ── Модельные фикстуры ───────────────────────────────────────────────────────

@pytest.fixture
def category(db):
    """Категория услуг."""
    return baker.make("services_app.ServiceCategory", name="Массаж")


@pytest.fixture
def service(db, category):
    """Активная услуга с уникальным slug."""
    return baker.make(
        "services_app.Service",
        name="Классический массаж",
        slug="test-slug",
        is_active=True,
        category=category,
    )


@pytest.fixture
def service_option(db, service):
    """Вариант услуги: 60 мин × 1 процедура, цена 3000."""
    return baker.make(
        "services_app.ServiceOption",
        service=service,
        duration_min=60,
        units=1,
        unit_type="session",
        price=Decimal("3000"),
        is_active=True,
        yclients_service_id="10000001",
    )


@pytest.fixture
def bundle(db):
    """Комплекс без фиксированной цены."""
    return baker.make(
        "services_app.Bundle",
        name="Комплекс SPA",
        fixed_price=None,
        discount=Decimal("0.00"),
        is_active=True,
    )


@pytest.fixture
def bundle_with_items(db, bundle, service):
    """Комплекс с двумя позициями (60 мин × 3000 руб и 30 мин × 1500 руб)."""
    opt1 = baker.make(
        "services_app.ServiceOption",
        service=service,
        duration_min=60,
        units=1,
        unit_type="session",
        price=Decimal("3000"),
    )
    opt2 = baker.make(
        "services_app.ServiceOption",
        service=service,
        duration_min=30,
        units=1,
        unit_type="zone",
        price=Decimal("1500"),
    )
    baker.make("services_app.BundleItem", bundle=bundle, option=opt1, quantity=1, parallel_group=1)
    baker.make("services_app.BundleItem", bundle=bundle, option=opt2, quantity=1, parallel_group=1)
    return bundle


# ── Мок YClients API ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_yclients_api():
    """Замокированный YClientsAPI."""
    api = MagicMock()
    api.company_id = "884045"
    api.get_staff.return_value = [
        {"id": 1, "name": "Анна", "specialization": "Массаж", "avatar": "", "rating": 5},
    ]
    api.get_book_dates.return_value = ["2026-03-01", "2026-03-02"]
    api.get_available_times.return_value = ["10:00", "11:00", "14:00"]
    api._request.return_value = {
        "success": True,
        "data": [
            {"time": "10:00", "seance_length": 3600},
            {"time": "11:00", "seance_length": 3600},
        ],
    }
    return api


@pytest.fixture
def mock_telegram(monkeypatch):
    """Заглушка Telegram (website.views.http_requests.post)."""
    mock = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr("website.views.http_requests.post", mock)
    return mock


# ── Заказы и сертификаты ────────────────────────────────────────────────────

@pytest.fixture
def order(db):
    """Заказ на сертификат."""
    return baker.make(
        "services_app.Order",
        order_type="certificate",
        status="pending",
        client_name="Иванов Иван",
        client_phone="+79991234567",
        total_amount=Decimal("3000"),
    )


@pytest.fixture
def gift_certificate(db, order, service):
    """Оплаченный подарочный сертификат на 3000 руб."""
    from datetime import date, timedelta
    return baker.make(
        "services_app.GiftCertificate",
        order=order,
        certificate_type="nominal",
        nominal=Decimal("3000"),
        buyer_name="Иванов Иван",
        buyer_phone="+79991234567",
        status="paid",
        valid_from=date.today(),
        valid_until=date.today() + timedelta(days=180),
        is_active=True,
    )
