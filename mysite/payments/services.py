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
        if order.service:
            return f"Оплата услуги: {order.service.name} ({order.number})"
        return f"Заказ {order.number}"
