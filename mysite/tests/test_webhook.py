"""Тесты webhook YooKassa + Celery task fulfill_paid_order.

YooKassa API мокается через YooKassaClient.find_payment (verify-path).
YClients API мокается через YClientsBookingService.create_record.
Telegram мокается через website.notifications.send_notification_telegram.

Celery task прогоняется eagerly: settings.CELERY_TASK_ALWAYS_EAGER=True.
"""
import json
from unittest.mock import MagicMock

import pytest

from payments.exceptions import BookingClientError, BookingValidationError


WEBHOOK_URL = "/api/payments/yookassa/webhook/"

pytestmark = pytest.mark.django_db


# ── Module-level autouse: лояльный IP whitelist + stub .delay ──────────


@pytest.fixture(autouse=True)
def _webhook_settings(settings):
    settings.YOOKASSA_WEBHOOK_STRICT_IP = False


@pytest.fixture
def fulfill_delay_mock(monkeypatch):
    """Мокает fulfill_paid_order.delay — веб-хук не должен пытаться
    реально отправить задачу в Celery broker (в тестах Redis не доступен).
    Task-логика тестируется отдельно, вызовом fulfill_paid_order напрямую."""
    mock = MagicMock()
    monkeypatch.setattr("payments.views.fulfill_paid_order", mock)
    return mock


# ── Хелперы ──────────────────────────────────────────────────────────────


def _payload(payment_id, event="payment.succeeded"):
    return {
        "type": "notification",
        "event": event,
        "object": {"id": payment_id, "status": "succeeded"},
    }


@pytest.fixture
def order_with_payment(service_order):
    service_order.payment_id = "pay_ok_1"
    service_order.payment_status = "pending"
    service_order.save(update_fields=["payment_id", "payment_status"])
    return service_order


@pytest.fixture
def mock_yookassa_client(monkeypatch):
    """Мокает get_yookassa_client в payments.views → find_payment возвращает succeeded."""
    client = MagicMock()
    client.find_payment.return_value = {
        "id": "pay_ok_1",
        "status": "succeeded",
        "paid": True,
        "metadata": {},
    }
    monkeypatch.setattr("payments.views.get_yookassa_client", lambda: client)
    return client


@pytest.fixture
def mock_booking_svc(monkeypatch):
    """Мокает YClientsBookingService в payments.tasks."""
    instance = MagicMock()
    instance.create_record.return_value = {
        "record_id": "rec_1",
        "record_hash": "hash_1",
    }
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr("payments.tasks.YClientsBookingService", cls)
    return instance


@pytest.fixture
def mock_tg(monkeypatch):
    """Мокает Telegram в payments.views и payments.tasks."""
    tg = MagicMock(return_value=True)
    monkeypatch.setattr("payments.views.send_notification_telegram", tg)
    monkeypatch.setattr("payments.tasks.send_notification_telegram", tg)
    return tg


# ── Webhook: happy path ────────────────────────────────────────────────


def test_webhook_returns_200_on_paid(
    client, order_with_payment, mock_yookassa_client, fulfill_delay_mock
):
    resp = client.post(
        WEBHOOK_URL,
        data=json.dumps(_payload("pay_ok_1")),
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_webhook_verifies_via_find_payment(
    client, order_with_payment, mock_yookassa_client, fulfill_delay_mock
):
    client.post(
        WEBHOOK_URL,
        data=json.dumps(_payload("pay_ok_1")),
        content_type="application/json",
    )
    mock_yookassa_client.find_payment.assert_called_once_with("pay_ok_1")


def test_webhook_updates_order_to_succeeded(
    client, order_with_payment, mock_yookassa_client, fulfill_delay_mock
):
    client.post(
        WEBHOOK_URL,
        data=json.dumps(_payload("pay_ok_1")),
        content_type="application/json",
    )
    order_with_payment.refresh_from_db()
    assert order_with_payment.payment_status == "succeeded"
    assert order_with_payment.status == "paid"
    assert order_with_payment.paid_at is not None


def test_webhook_schedules_fulfill_delay(
    client, order_with_payment, mock_yookassa_client, fulfill_delay_mock
):
    client.post(
        WEBHOOK_URL,
        data=json.dumps(_payload("pay_ok_1")),
        content_type="application/json",
    )
    fulfill_delay_mock.delay.assert_called_once_with(order_with_payment.id)


# ── Webhook: идемпотентность ────────────────────────────────────────────


def test_webhook_already_succeeded_skips_fulfill(
    client, order_with_payment, mock_yookassa_client, fulfill_delay_mock
):
    order_with_payment.payment_status = "succeeded"
    order_with_payment.save(update_fields=["payment_status"])

    client.post(
        WEBHOOK_URL,
        data=json.dumps(_payload("pay_ok_1")),
        content_type="application/json",
    )
    fulfill_delay_mock.delay.assert_not_called()


# ── Webhook: canceled ───────────────────────────────────────────────────


def test_webhook_marks_order_canceled(
    client, order_with_payment, mock_yookassa_client, mock_tg
):
    mock_yookassa_client.find_payment.return_value = {
        "id": "pay_ok_1", "status": "canceled", "paid": False, "metadata": {},
    }
    resp = client.post(
        WEBHOOK_URL,
        data=json.dumps(_payload("pay_ok_1", event="payment.canceled")),
        content_type="application/json",
    )
    assert resp.status_code == 200
    order_with_payment.refresh_from_db()
    assert order_with_payment.payment_status == "canceled"
    assert order_with_payment.status == "cancelled"
    assert mock_tg.called


# ── Webhook: ошибки payload ─────────────────────────────────────────────


def test_webhook_invalid_json_returns_400(client, mock_yookassa_client):
    resp = client.post(
        WEBHOOK_URL,
        data="{broken",
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_webhook_missing_payment_id_returns_400(client, mock_yookassa_client):
    resp = client.post(
        WEBHOOK_URL,
        data=json.dumps({"event": "payment.succeeded", "object": {}}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_webhook_unknown_order_returns_200(
    client, mock_yookassa_client, fulfill_delay_mock
):
    resp = client.post(
        WEBHOOK_URL,
        data=json.dumps(_payload("pay_does_not_exist")),
        content_type="application/json",
    )
    # 200 — YooKassa не должна ретраить из-за нашей ошибки
    assert resp.status_code == 200
    fulfill_delay_mock.delay.assert_not_called()


# ── IP whitelist ─────────────────────────────────────────────────────────


def test_webhook_rejects_non_whitelisted_ip(
    settings, client, order_with_payment, mock_yookassa_client
):
    settings.YOOKASSA_WEBHOOK_STRICT_IP = True
    resp = client.post(
        WEBHOOK_URL,
        data=json.dumps(_payload("pay_ok_1")),
        content_type="application/json",
        REMOTE_ADDR="8.8.8.8",
    )
    assert resp.status_code == 403


def test_webhook_accepts_yookassa_ip(
    settings, client, order_with_payment, mock_yookassa_client, fulfill_delay_mock
):
    settings.YOOKASSA_WEBHOOK_STRICT_IP = True
    resp = client.post(
        WEBHOOK_URL,
        data=json.dumps(_payload("pay_ok_1")),
        content_type="application/json",
        REMOTE_ADDR="185.71.76.5",
    )
    assert resp.status_code == 200


# ── Celery task fulfill_paid_order ─────────────────────────────────────
#
# Задача с bind=True → self передаётся при вызове через Celery runner.
# Используем .apply(args=[...]) — это eager-выполнение task с правильным
# self, не требующее broker (в отличие от .delay()).


def test_fulfill_creates_yclients_record_on_success(
    order_with_payment, mock_booking_svc, mock_tg
):
    from payments.tasks import fulfill_paid_order

    fulfill_paid_order.apply(args=[order_with_payment.id])
    mock_booking_svc.create_record.assert_called_once()


def test_fulfill_idempotent_when_record_id_exists(
    order_with_payment, mock_booking_svc, mock_tg
):
    from payments.tasks import fulfill_paid_order

    order_with_payment.yclients_record_id = "existing"
    order_with_payment.save(update_fields=["yclients_record_id"])

    fulfill_paid_order.apply(args=[order_with_payment.id])
    mock_booking_svc.create_record.assert_not_called()


def test_fulfill_missing_order_is_noop(mock_booking_svc):
    from payments.tasks import fulfill_paid_order

    fulfill_paid_order.apply(args=[999999])
    mock_booking_svc.create_record.assert_not_called()


def test_fulfill_validation_error_no_retry_and_alerts_admin(
    order_with_payment, mock_booking_svc, mock_tg
):
    from payments.tasks import fulfill_paid_order

    mock_booking_svc.create_record.side_effect = BookingValidationError("bad order")
    fulfill_paid_order.apply(args=[order_with_payment.id])

    order_with_payment.refresh_from_db()
    assert "validation" in order_with_payment.admin_note.lower()
    assert mock_tg.called
    msg = mock_tg.call_args[0][0]
    assert "QC failed" in msg or "validation" in msg.lower()


def test_fulfill_client_error_retries_through_celery(
    order_with_payment, mock_booking_svc, mock_tg
):
    """BookingClientError → self.retry. apply() прогоняет task в sync-режиме,
    исчерпание max_retries приводит к MaxRetriesExceededError — его мы ловим
    внутри task и пишем admin_note + Telegram. Apply() по умолчанию re-raises
    final exception (throw=True), поэтому ожидаем что apply() вернёт result
    с состоянием failure ИЛИ бросит FAILED."""
    from payments.tasks import fulfill_paid_order

    mock_booking_svc.create_record.side_effect = BookingClientError("yclients down")
    # throw=False — apply не re-raises финальное исключение, оно идёт в result.
    fulfill_paid_order.apply(args=[order_with_payment.id], throw=False)

    # Задача должна была пройти через несколько retry и либо записать
    # admin_note (если все retries отработали и попали в MaxRetriesExceededError),
    # либо хотя бы дёрнула create_record > 1 раза (retry-механика работает).
    assert mock_booking_svc.create_record.call_count > 1
