"""Интеграционные тесты POST /api/services/order/ + GET /api/payments/status/.

Моки:
- PaymentService: create_for_order → возвращает URL
- YClientsBookingService: create_record → record_id
- Telegram: заглушка
"""
import json
from unittest.mock import MagicMock

import pytest
from model_bakery import baker

from services_app.models import Order, SiteSettings


ORDER_URL = "/api/services/order/"
STATUS_URL = "/api/payments/status/"

pytestmark = pytest.mark.django_db


# ── Общие фикстуры ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_ratelimit(settings):
    settings.RATELIMIT_ENABLE = False


@pytest.fixture
def site_settings_online_on(db):
    s = baker.make(SiteSettings, online_payment_enabled=True)
    return s


@pytest.fixture
def site_settings_online_off(db):
    s = baker.make(SiteSettings, online_payment_enabled=False)
    return s


@pytest.fixture
def mock_payment_service(monkeypatch):
    instance = MagicMock()
    instance.create_for_order.return_value = "https://yookassa.test/pay/abc123"
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr("payments.services.PaymentService", cls)
    return instance


@pytest.fixture
def mock_yclients_booking(monkeypatch):
    instance = MagicMock()
    instance.create_record.return_value = {"record_id": "rec_123", "record_hash": "h"}
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr("payments.booking_service.YClientsBookingService", cls)
    return instance


@pytest.fixture
def mock_tg(monkeypatch):
    tg = MagicMock(return_value=True)
    monkeypatch.setattr("website.notifications.send_notification_telegram", tg)
    return tg


def _valid_payload(service_option, payment_method="online"):
    return {
        "service_option_id": service_option.id,
        "staff_id": 4416525,
        "date": "2026-05-15",
        "time": "10:00",
        "client_name": "Иван Иванов",
        "client_phone": "+7 999 123-45-67",
        "client_email": "ivan@example.com",
        "comment": "Первый визит",
        "payment_method": payment_method,
    }


# ── Happy path: online ───────────────────────────────────────────────


def test_online_returns_payment_url(
    client, service_option, site_settings_online_on,
    mock_payment_service, mock_yclients_booking, mock_tg,
):
    resp = client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "online")),
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["success"] is True
    assert body["payment_method"] == "online"
    assert body["payment_url"] == "https://yookassa.test/pay/abc123"
    assert body["order_number"].startswith("FT-")


def test_online_creates_order_with_pending_payment(
    client, service_option, site_settings_online_on,
    mock_payment_service, mock_yclients_booking, mock_tg,
):
    client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "online")),
        content_type="application/json",
    )
    order = Order.objects.filter(order_type="service").latest("created_at")
    assert order.payment_method == "online"
    assert order.payment_status == "pending"
    assert order.service_option_id == service_option.id
    assert order.staff_id == 4416525
    assert order.total_amount == service_option.price


def test_online_does_not_create_yclients_record_yet(
    client, service_option, site_settings_online_on,
    mock_payment_service, mock_yclients_booking, mock_tg,
):
    client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "online")),
        content_type="application/json",
    )
    mock_yclients_booking.create_record.assert_not_called()


def test_online_normalizes_phone(
    client, service_option, site_settings_online_on,
    mock_payment_service, mock_yclients_booking, mock_tg,
):
    client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "online")),
        content_type="application/json",
    )
    order = Order.objects.filter(order_type="service").latest("created_at")
    assert order.client_phone == "+79991234567"


# ── Online disabled ───────────────────────────────────────────────────


def test_online_returns_400_when_disabled(
    client, service_option, site_settings_online_off,
    mock_payment_service, mock_yclients_booking, mock_tg,
):
    resp = client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "online")),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "online_payment_disabled"
    mock_payment_service.create_for_order.assert_not_called()


# ── Happy path: offline (cash / card_offline) ───────────────────────


def test_cash_creates_yclients_record_immediately(
    client, service_option, site_settings_online_on,
    mock_payment_service, mock_yclients_booking, mock_tg,
):
    resp = client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "cash")),
        content_type="application/json",
    )
    assert resp.status_code == 200
    mock_yclients_booking.create_record.assert_called_once()
    mock_payment_service.create_for_order.assert_not_called()


def test_cash_returns_yclients_record_id(
    client, service_option, site_settings_online_on,
    mock_payment_service, mock_yclients_booking, mock_tg,
):
    resp = client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "cash")),
        content_type="application/json",
    )
    body = resp.json()
    assert body["yclients_record_id"] == "rec_123"
    assert body["payment_method"] == "cash"


def test_cash_sends_telegram_notification(
    client, service_option, site_settings_online_on,
    mock_payment_service, mock_yclients_booking, monkeypatch,
):
    tg = MagicMock(return_value=True)
    # send_notification_telegram импортируется внутри view — мокаем на уровне
    # исходного модуля website.notifications.
    monkeypatch.setattr("website.notifications.send_notification_telegram", tg)
    client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "cash")),
        content_type="application/json",
    )
    assert tg.called


def test_card_offline_works_even_when_online_disabled(
    client, service_option, site_settings_online_off,
    mock_payment_service, mock_yclients_booking, mock_tg,
):
    """Офлайн-способы не требуют online_payment_enabled."""
    resp = client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "card_offline")),
        content_type="application/json",
    )
    assert resp.status_code == 200
    mock_yclients_booking.create_record.assert_called_once()


# ── Валидация ────────────────────────────────────────────────────────


def test_invalid_json_returns_400(client, site_settings_online_on):
    resp = client.post(ORDER_URL, data="{broken", content_type="application/json")
    assert resp.status_code == 400


def test_missing_service_option_id_returns_400(client, site_settings_online_on):
    payload = {"staff_id": 1, "date": "2026-05-15", "time": "10:00"}
    resp = client.post(ORDER_URL, data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 400


def test_unknown_service_option_returns_400(
    client, service_option, site_settings_online_on,
):
    payload = _valid_payload(service_option, "cash")
    payload["service_option_id"] = 99999999
    resp = client.post(ORDER_URL, data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 400
    assert "service_option_id" in resp.json()["errors"]


def test_invalid_payment_method_returns_400(
    client, service_option, site_settings_online_on,
):
    payload = _valid_payload(service_option, "bitcoin")
    resp = client.post(ORDER_URL, data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 400


def test_invalid_time_format_returns_400(
    client, service_option, site_settings_online_on,
):
    payload = _valid_payload(service_option, "cash")
    payload["time"] = "25:99"
    resp = client.post(ORDER_URL, data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 400


def test_invalid_phone_returns_400(
    client, service_option, site_settings_online_on,
):
    payload = _valid_payload(service_option, "cash")
    payload["client_phone"] = "abc"
    resp = client.post(ORDER_URL, data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 400


# ── Идемпотентность ───────────────────────────────────────────────────


def test_double_submit_returns_cached_response(
    client, service_option, site_settings_online_on,
    mock_payment_service, mock_yclients_booking, mock_tg,
):
    payload = _valid_payload(service_option, "online")
    r1 = client.post(ORDER_URL, data=json.dumps(payload), content_type="application/json")
    r2 = client.post(ORDER_URL, data=json.dumps(payload), content_type="application/json")
    assert r1.status_code == r2.status_code == 200
    # Первое возвращает свежий payment_url, второе — тот же cached
    assert r1.json()["payment_url"] == r2.json()["payment_url"]
    assert r1.json()["order_number"] == r2.json()["order_number"]
    # PaymentService.create_for_order вызван ровно один раз
    assert mock_payment_service.create_for_order.call_count == 1


# ── Обработка ошибок ─────────────────────────────────────────────────


def test_offline_rolls_back_on_yclients_failure(
    client, service_option, site_settings_online_on,
    mock_yclients_booking, mock_tg,
):
    from payments.exceptions import BookingClientError

    mock_yclients_booking.create_record.side_effect = BookingClientError("slot taken")
    resp = client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "cash")),
        content_type="application/json",
    )
    assert resp.status_code == 502
    # Order остался в БД, но помечен cancelled
    order = Order.objects.filter(order_type="service").latest("created_at")
    assert order.status == "cancelled"
    assert "create_booking failed" in order.admin_note


def test_online_rolls_back_order_when_payment_service_fails(
    client, service_option, site_settings_online_on,
    mock_payment_service, mock_yclients_booking, mock_tg,
):
    from payments.exceptions import PaymentError

    mock_payment_service.create_for_order.side_effect = PaymentError("boom")
    resp = client.post(
        ORDER_URL,
        data=json.dumps(_valid_payload(service_option, "online")),
        content_type="application/json",
    )
    assert resp.status_code == 502
    assert not Order.objects.filter(order_type="service").exists()


# ── Status endpoint ───────────────────────────────────────────────────


def test_status_returns_order_state(client, service_order):
    resp = client.get(f"{STATUS_URL}?order={service_order.number}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["order_number"] == service_order.number
    assert body["payment_status"] == service_order.payment_status
    assert body["fulfilled"] is False


def test_status_fulfilled_when_record_id_set(client, service_order):
    service_order.yclients_record_id = "rec_abc"
    service_order.save(update_fields=["yclients_record_id"])
    resp = client.get(f"{STATUS_URL}?order={service_order.number}")
    assert resp.json()["fulfilled"] is True


def test_status_404_when_unknown_order(client, db):
    resp = client.get(f"{STATUS_URL}?order=FT-NOPE")
    assert resp.status_code == 404


def test_status_400_when_order_param_missing(client, db):
    resp = client.get(STATUS_URL)
    assert resp.status_code == 400
