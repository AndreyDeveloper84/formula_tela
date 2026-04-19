"""PaymentService — бизнес-логика создания YooKassa-платежа под Order.

Service Object: одна ответственность, DI через конструктор (client), factory
из settings по-умолчанию. Не знает про views/Celery — чистая логика поверх
YooKassaClient и Order.
"""
import logging

from django.conf import settings

from payments.exceptions import PaymentError
from payments.yookassa_client import YooKassaClient, get_yookassa_client
from services_app.models import Order

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(self, client: YooKassaClient | None = None):
        self._client = client or get_yookassa_client()

    def create_for_order(self, order: Order) -> str:
        """Создать платёж под Order, сохранить payment_id/url/status,
        вернуть confirmation_url для редиректа клиента.

        Идемпотентно по Order.number — повторный вызов с тем же ключом не
        создаст дубль платежа на стороне YooKassa.
        """
        if order.payment_method != "online":
            raise PaymentError(
                f"Order {order.number}: payment_method={order.payment_method!r}, "
                f"online expected"
            )
        if order.total_amount <= 0:
            raise PaymentError(
                f"Order {order.number}: total_amount must be > 0 (got {order.total_amount})"
            )

        return_url = settings.YOOKASSA_RETURN_URL.format(order_number=order.number)
        result = self._client.create_payment(
            amount=order.total_amount,
            description=self._build_description(order),
            return_url=return_url,
            metadata={"order_id": str(order.id), "order_number": order.number},
            idempotence_key=order.number,
            receipt=self._build_receipt(order),
        )
        order.payment_id = result["id"]
        order.payment_url = result["confirmation_url"]
        order.payment_status = "pending"
        order.save(
            update_fields=["payment_id", "payment_url", "payment_status", "updated_at"]
        )
        logger.info(
            "YooKassa payment created: order=%s payment_id=%s", order.number, result["id"]
        )
        return result["confirmation_url"]

    def _build_description(self, order: Order) -> str:
        if order.order_type == "certificate":
            cert = order.certificates.first()
            if cert and cert.certificate_type == "nominal":
                return f"Подарочный сертификат на {cert.nominal} ₽ ({order.number})"
            if cert and cert.service:
                return f"Подарочный сертификат: {cert.service.name} ({order.number})"
            return f"Подарочный сертификат ({order.number})"
        if order.order_type == "bundle":
            bundle = order.bundle
            return f"Комплекс: {bundle.name} ({order.number})" if bundle else f"Комплекс {order.number}"
        if order.service:
            return f"Оплата услуги: {order.service.name} ({order.number})"
        return f"Заказ {order.number}"

    def _build_receipt(self, order: Order) -> dict:
        customer = {}
        if order.client_phone:
            customer["phone"] = order.client_phone
        if order.client_email:
            customer["email"] = order.client_email

        vat_code = getattr(settings, "YOOKASSA_VAT_CODE", 1)

        if order.order_type == "certificate":
            cert = order.certificates.first()
            if cert and cert.certificate_type == "nominal":
                item_desc = f"Подарочный сертификат на {cert.nominal} ₽"
            elif cert and cert.service:
                item_desc = f"Подарочный сертификат: {cert.service.name}"
            else:
                item_desc = "Подарочный сертификат"
            payment_subject = "payment"
        elif order.order_type == "bundle":
            bundle = order.bundle
            item_desc = f"Комплекс: {bundle.name}" if bundle else f"Комплекс {order.number}"
            payment_subject = "service"
        else:
            if order.service:
                item_desc = order.service.name
                if order.service_option and order.service_option.name:
                    item_desc = f"{item_desc} — {order.service_option.name}"
            else:
                item_desc = f"Заказ {order.number}"
            payment_subject = "service"

        return {
            "customer": customer,
            "items": [{
                "description": item_desc[:128],
                "quantity": "1.00",
                "amount": {"value": f"{order.total_amount:.2f}", "currency": "RUB"},
                "vat_code": vat_code,
                "payment_mode": "full_payment",
                "payment_subject": payment_subject,
            }],
        }
