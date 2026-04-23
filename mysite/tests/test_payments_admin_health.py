"""Тесты OrderAdmin.action_recreate_payment_link и /api/agents/health/
секции payments."""
import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.contrib.admin.sites import AdminSite
from django.utils import timezone
from model_bakery import baker

# После P2 рефакторинга OrderAdmin с payment-actions живёт в payments/admin.py.
# services_app/admin.py содержит base-admin без payment-специфики.
from payments.admin import OrderAdmin
from services_app.models import Order, SiteSettings


pytestmark = pytest.mark.django_db


# ── OrderAdmin action_recreate_payment_link ────────────────────────────


@pytest.fixture
def admin_order_online_pending(db, service, service_option):
    return baker.make(
        Order,
        order_type="service",
        payment_method="online",
        payment_status="pending",
        payment_id="old_pay_id",
        payment_url="https://yookassa.test/old",
        total_amount=Decimal("1500"),
        service=service,
        service_option=service_option,
        client_name="A",
        client_phone="+79991112233",
    )


@pytest.fixture
def admin_order_cash(db, service, service_option):
    return baker.make(
        Order,
        order_type="service",
        payment_method="cash",
        payment_status="not_required",
        total_amount=Decimal("1500"),
        service=service,
        service_option=service_option,
        client_name="B",
        client_phone="+79991112244",
    )


@pytest.fixture
def admin_mock_payment_service(monkeypatch):
    instance = MagicMock()

    def fake_create(order):
        order.payment_id = "new_pay"
        order.payment_url = "https://yookassa.test/new"
        order.payment_status = "pending"
        order.save(update_fields=["payment_id", "payment_url", "payment_status", "updated_at"])
        return order.payment_url

    instance.create_for_order.side_effect = fake_create
    monkeypatch.setattr("payments.services.PaymentService", MagicMock(return_value=instance))
    return instance


def _run_admin_action(order_admin, queryset, request=None):
    request = request or MagicMock()
    request._messages = MagicMock()
    order_admin.action_recreate_payment_link(request, queryset)


def test_recreate_regenerates_payment_url_for_online_pending(
    admin_order_online_pending, admin_mock_payment_service
):
    adm = OrderAdmin(Order, AdminSite())
    _run_admin_action(adm, Order.objects.filter(pk=admin_order_online_pending.pk))
    admin_order_online_pending.refresh_from_db()
    assert admin_order_online_pending.payment_url == "https://yookassa.test/new"
    assert admin_order_online_pending.payment_id == "new_pay"
    admin_mock_payment_service.create_for_order.assert_called_once()


def test_recreate_skips_cash_orders(admin_order_cash, admin_mock_payment_service):
    adm = OrderAdmin(Order, AdminSite())
    _run_admin_action(adm, Order.objects.filter(pk=admin_order_cash.pk))
    admin_mock_payment_service.create_for_order.assert_not_called()


def test_recreate_adds_note_on_failure(admin_order_online_pending, monkeypatch):
    from payments.exceptions import PaymentError

    svc = MagicMock()
    svc.create_for_order.side_effect = PaymentError("YooKassa down")
    monkeypatch.setattr("payments.services.PaymentService", MagicMock(return_value=svc))

    adm = OrderAdmin(Order, AdminSite())
    _run_admin_action(adm, Order.objects.filter(pk=admin_order_online_pending.pk))

    admin_order_online_pending.refresh_from_db()
    assert "[recreate]" in admin_order_online_pending.admin_note
    assert "YooKassa down" in admin_order_online_pending.admin_note


# ── /api/agents/health/ секция payments ────────────────────────────────


HEALTH_URL = "/api/agents/health/"


def test_health_returns_payments_section(client, db):
    resp = client.get(HEALTH_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert "payments" in body
    p = body["payments"]
    assert "pending_24h" in p
    assert "pending_over_1h" in p
    assert "succeeded_24h" in p
    assert "canceled_24h" in p
    assert "failed_fulfill_24h" in p
    assert "online_payment_enabled" in p


def test_health_reflects_online_payment_flag(client, db):
    SiteSettings.objects.all().delete()
    baker.make(SiteSettings, online_payment_enabled=True)
    resp = client.get(HEALTH_URL)
    assert resp.json()["payments"]["online_payment_enabled"] is True


def test_health_counts_pending_orders(client, db, service, service_option):
    # 1 pending недавний + 1 succeeded
    baker.make(
        Order, order_type="service", payment_method="online",
        payment_status="pending", service=service, service_option=service_option,
        client_name="P", client_phone="+79001",
    )
    baker.make(
        Order, order_type="service", payment_method="online",
        payment_status="succeeded", service=service, service_option=service_option,
        client_name="S", client_phone="+79002",
    )
    resp = client.get(HEALTH_URL)
    p = resp.json()["payments"]
    assert p["pending_24h"] == 1
    assert p["succeeded_24h"] == 1


def test_health_counts_failed_fulfill(client, db, service, service_option):
    # Paid >5 мин назад, yclients_record_id пустой → failed_fulfill
    past = timezone.now() - datetime.timedelta(minutes=30)
    o = baker.make(
        Order, order_type="service", payment_method="online",
        payment_status="succeeded",
        yclients_record_id="",
        service=service, service_option=service_option,
        client_name="F", client_phone="+79003",
    )
    Order.objects.filter(pk=o.pk).update(paid_at=past)

    resp = client.get(HEALTH_URL)
    assert resp.json()["payments"]["failed_fulfill_24h"] == 1
    assert resp.json()["status"] == "unhealthy"


def test_health_healthy_when_no_payment_issues(client, db):
    # Нет Order-ов service → всё нули
    resp = client.get(HEALTH_URL)
    p = resp.json()["payments"]
    assert p["pending_24h"] == 0
    assert p["failed_fulfill_24h"] == 0
