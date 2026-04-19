"""Unit-тесты для payments.yookassa_client и payments.services.

SDK (yookassa.Payment.create / find_one / Configuration.configure) мокается —
в CI реальные creds пусты, а даже с ними дёргать боевой API в тестах нельзя.
Мокаем через monkeypatch по паттерну mock_yclients_api в conftest.py.
"""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from payments.exceptions import (
    PaymentClientError,
    PaymentConfigError,
    PaymentError,
)
from payments.services import PaymentService
from payments.yookassa_client import YooKassaClient


# ── Хелперы ──────────────────────────────────────────────────────────────


def _fake_sdk_payment(
    *,
    id_="pay_test_1",
    status="pending",
    confirmation_url="https://yookassa.test/confirm/pay_test_1",
    paid=False,
    metadata=None,
):
    """Имитирует yookassa.domain.models.PaymentResponse."""
    p = MagicMock()
    p.id = id_
    p.status = status
    p.paid = paid
    p.metadata = metadata or {}
    p.confirmation = MagicMock()
    p.confirmation.confirmation_url = confirmation_url
    return p


@pytest.fixture
def sdk_mocks(monkeypatch):
    """Мокает Configuration.configure, Payment.create, Payment.find_one.

    Возвращает объект с атрибутами .configure, .create, .find_one — это
    MagicMock'и, чтобы тесты могли assert_called_with / side_effect.
    """
    configure = MagicMock()
    create = MagicMock(return_value=_fake_sdk_payment())
    find_one = MagicMock(return_value=_fake_sdk_payment(status="succeeded", paid=True))
    monkeypatch.setattr("payments.yookassa_client.Configuration.configure", configure)
    monkeypatch.setattr("payments.yookassa_client.Payment.create", create)
    monkeypatch.setattr("payments.yookassa_client.Payment.find_one", find_one)
    mocks = MagicMock()
    mocks.configure = configure
    mocks.create = create
    mocks.find_one = find_one
    return mocks


# ── YooKassaClient ───────────────────────────────────────────────────────


class TestYooKassaClientInit:
    def test_raises_config_error_when_shop_id_empty(self):
        with pytest.raises(PaymentConfigError):
            YooKassaClient(shop_id="", secret_key="sk")

    def test_raises_config_error_when_secret_empty(self):
        with pytest.raises(PaymentConfigError):
            YooKassaClient(shop_id="123", secret_key="")

    def test_configures_sdk_on_init(self, sdk_mocks):
        YooKassaClient(shop_id="shop123", secret_key="secret_abc")
        sdk_mocks.configure.assert_called_once_with("shop123", "secret_abc")


class TestYooKassaClientCreatePayment:
    def test_returns_dict_with_id_status_url(self, sdk_mocks):
        client = YooKassaClient(shop_id="s", secret_key="k")
        result = client.create_payment(
            amount=Decimal("3000"),
            description="Test",
            return_url="https://r.test/ok",
            metadata={"order_id": "1"},
            idempotence_key="FT-00001",
        )
        assert result == {
            "id": "pay_test_1",
            "status": "pending",
            "confirmation_url": "https://yookassa.test/confirm/pay_test_1",
        }

    def test_passes_idempotence_key(self, sdk_mocks):
        client = YooKassaClient(shop_id="s", secret_key="k")
        client.create_payment(
            amount=Decimal("100"),
            description="x",
            return_url="https://r/ok",
            metadata={},
            idempotence_key="FT-00042",
        )
        # Payment.create(payload, idempotence_key)
        args, _ = sdk_mocks.create.call_args
        assert args[1] == "FT-00042"

    def test_payload_has_amount_currency_and_capture(self, sdk_mocks):
        client = YooKassaClient(shop_id="s", secret_key="k")
        client.create_payment(
            amount=Decimal("1500"),
            description="desc",
            return_url="https://r/ok",
            metadata={"a": "b"},
            idempotence_key="k1",
        )
        payload = sdk_mocks.create.call_args.args[0]
        assert payload["amount"] == {"value": "1500.00", "currency": "RUB"}
        assert payload["confirmation"] == {
            "type": "redirect",
            "return_url": "https://r/ok",
        }
        assert payload["capture"] is True
        assert payload["metadata"] == {"a": "b"}

    def test_wraps_api_error_into_client_error(self, sdk_mocks):
        from yookassa.domain.exceptions import ApiError

        sdk_mocks.create.side_effect = ApiError({"code": "invalid_request", "description": "boom"})
        client = YooKassaClient(shop_id="s", secret_key="k")
        with pytest.raises(PaymentClientError):
            client.create_payment(
                amount=Decimal("10"),
                description="x",
                return_url="https://r/ok",
                metadata={},
                idempotence_key="k",
            )


class TestYooKassaClientFindPayment:
    def test_returns_normalized_dict(self, sdk_mocks):
        sdk_mocks.find_one.return_value = _fake_sdk_payment(
            id_="pay_2", status="succeeded", paid=True, metadata={"order_id": "42"}
        )
        client = YooKassaClient(shop_id="s", secret_key="k")
        result = client.find_payment("pay_2")
        assert result == {
            "id": "pay_2",
            "status": "succeeded",
            "paid": True,
            "metadata": {"order_id": "42"},
        }

    def test_wraps_api_error(self, sdk_mocks):
        from yookassa.domain.exceptions import ApiError

        sdk_mocks.find_one.side_effect = ApiError({"code": "not_found", "description": "not found"})
        client = YooKassaClient(shop_id="s", secret_key="k")
        with pytest.raises(PaymentClientError):
            client.find_payment("pay_missing")


# ── PaymentService ───────────────────────────────────────────────────────


@pytest.fixture
def fake_client():
    """Мок YooKassaClient — инжектится в PaymentService через DI."""
    client = MagicMock(spec=YooKassaClient)
    client.create_payment.return_value = {
        "id": "pay_mock_1",
        "status": "pending",
        "confirmation_url": "https://yookassa.test/pay/pay_mock_1",
    }
    return client


class TestPaymentServiceCreateForOrder:
    def test_returns_confirmation_url(self, fake_client, service_order):
        svc = PaymentService(client=fake_client)
        url = svc.create_for_order(service_order)
        assert url == "https://yookassa.test/pay/pay_mock_1"

    def test_persists_payment_id_and_url_on_order(self, fake_client, service_order):
        svc = PaymentService(client=fake_client)
        svc.create_for_order(service_order)
        service_order.refresh_from_db()
        assert service_order.payment_id == "pay_mock_1"
        assert service_order.payment_url == "https://yookassa.test/pay/pay_mock_1"

    def test_sets_payment_status_pending(self, fake_client, service_order):
        assert service_order.payment_status == "not_required"
        svc = PaymentService(client=fake_client)
        svc.create_for_order(service_order)
        service_order.refresh_from_db()
        assert service_order.payment_status == "pending"

    def test_uses_order_number_as_idempotence_key(self, fake_client, service_order):
        svc = PaymentService(client=fake_client)
        svc.create_for_order(service_order)
        kwargs = fake_client.create_payment.call_args.kwargs
        assert kwargs["idempotence_key"] == service_order.number

    def test_metadata_contains_order_id_and_number(self, fake_client, service_order):
        svc = PaymentService(client=fake_client)
        svc.create_for_order(service_order)
        kwargs = fake_client.create_payment.call_args.kwargs
        assert kwargs["metadata"] == {
            "order_id": str(service_order.id),
            "order_number": service_order.number,
        }

    def test_return_url_contains_order_number(self, fake_client, service_order):
        svc = PaymentService(client=fake_client)
        svc.create_for_order(service_order)
        kwargs = fake_client.create_payment.call_args.kwargs
        assert service_order.number in kwargs["return_url"]

    def test_description_contains_service_name_and_order_number(
        self, fake_client, service_order
    ):
        svc = PaymentService(client=fake_client)
        svc.create_for_order(service_order)
        kwargs = fake_client.create_payment.call_args.kwargs
        assert service_order.service.name in kwargs["description"]
        assert service_order.number in kwargs["description"]

    def test_raises_when_payment_method_not_online(self, fake_client, service_order):
        service_order.payment_method = "cash"
        service_order.save(update_fields=["payment_method"])
        svc = PaymentService(client=fake_client)
        with pytest.raises(PaymentError):
            svc.create_for_order(service_order)
        fake_client.create_payment.assert_not_called()

    def test_raises_when_total_amount_zero(self, fake_client, service_order):
        service_order.total_amount = Decimal("0")
        service_order.save(update_fields=["total_amount"])
        svc = PaymentService(client=fake_client)
        with pytest.raises(PaymentError):
            svc.create_for_order(service_order)
        fake_client.create_payment.assert_not_called()

    def test_create_for_order_passes_receipt_to_client(self, fake_client, service_order):
        svc = PaymentService(client=fake_client)
        svc.create_for_order(service_order)
        kwargs = fake_client.create_payment.call_args.kwargs
        assert "receipt" in kwargs
        assert "customer" in kwargs["receipt"]
        assert "items" in kwargs["receipt"]

    def test_receipt_contains_customer_phone(self, fake_client, service_order):
        service_order.client_phone = "+79001112233"
        service_order.save(update_fields=["client_phone"])
        svc = PaymentService(client=fake_client)
        receipt = svc._build_receipt(service_order)
        assert receipt["customer"]["phone"] == "+79001112233"

    def test_receipt_contains_customer_email_when_set(self, fake_client, service_order):
        service_order.client_email = "test@example.com"
        service_order.save(update_fields=["client_email"])
        svc = PaymentService(client=fake_client)
        receipt = svc._build_receipt(service_order)
        assert receipt["customer"]["email"] == "test@example.com"

    def test_receipt_item_uses_service_name(self, fake_client, service_order):
        svc = PaymentService(client=fake_client)
        receipt = svc._build_receipt(service_order)
        assert service_order.service.name in receipt["items"][0]["description"]
