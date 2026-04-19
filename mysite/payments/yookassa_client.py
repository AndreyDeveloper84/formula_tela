"""Тонкий wrapper над YooKassa Python SDK.

Изолирует SDK от бизнес-логики: PaymentService принимает YooKassaClient через
DI и получает из него чистые dict'ы без SDK-типов. По аналогии с
services_app/yclients_api.py::YClientsAPI и get_yclients_api().
"""
import logging
from decimal import Decimal

from django.conf import settings
from yookassa import Configuration, Payment
from yookassa.domain.exceptions import ApiError

from payments.exceptions import PaymentClientError, PaymentConfigError

logger = logging.getLogger(__name__)


class YooKassaClient:
    """Минимальный HTTP-клиент YooKassa.

    Два метода: create_payment и find_payment. Оба возвращают чистые dict'ы
    с отфильтрованными полями — чтобы caller (PaymentService) не зависел
    от структуры yookassa.domain.models.*.
    """

    def __init__(self, shop_id: str, secret_key: str):
        if not shop_id or not secret_key:
            raise PaymentConfigError(
                "YooKassa credentials not configured "
                "(YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY пусты)"
            )
        Configuration.configure(shop_id, secret_key)
        self.shop_id = shop_id

    def create_payment(
        self,
        *,
        amount: Decimal,
        description: str,
        return_url: str,
        metadata: dict,
        idempotence_key: str,
    ) -> dict:
        """Создать платёж. Возвращает {id, status, confirmation_url}."""
        payload = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description,
            "metadata": metadata,
            "capture": True,
        }
        try:
            payment = Payment.create(payload, idempotence_key)
        except ApiError as exc:
            logger.exception("YooKassa create_payment failed: %s", exc)
            raise PaymentClientError(f"YooKassa API error: {exc}") from exc

        return {
            "id": payment.id,
            "status": payment.status,
            "confirmation_url": payment.confirmation.confirmation_url,
        }

    def find_payment(self, payment_id: str) -> dict:
        """Получить платёж по id. Для verify после webhook."""
        try:
            payment = Payment.find_one(payment_id)
        except ApiError as exc:
            logger.exception("YooKassa find_payment failed: %s", exc)
            raise PaymentClientError(f"YooKassa API error: {exc}") from exc

        return {
            "id": payment.id,
            "status": payment.status,
            "paid": bool(payment.paid),
            "metadata": dict(payment.metadata or {}),
        }


def get_yookassa_client() -> YooKassaClient:
    """Factory: собирает клиент из settings. Бросает PaymentConfigError если
    creds пусты — caller должен ловить это и показывать клиенту оффлайн-опции."""
    return YooKassaClient(
        shop_id=settings.YOOKASSA_SHOP_ID,
        secret_key=settings.YOOKASSA_SECRET_KEY,
    )
