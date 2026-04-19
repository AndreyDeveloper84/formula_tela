"""Celery-таски подсистемы оплат.

Основная: fulfill_paid_order(order_id) — вызывается из webhook после
успешной оплаты. Создаёт YClients-запись через YClientsBookingService
и шлёт Telegram-уведомление админу.

Retry-поведение:
- BookingValidationError — фатально, не ретраим (Order не в том состоянии,
  нужен ручной разбор админом).
- BookingClientError — временный сбой YClients/сети, retry с exponential
  backoff до max_retries=5. После исчерпания retry — Order помечается в
  admin_note и шлётся алерт админу.
"""
import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from django.utils import timezone

from payments.booking_service import YClientsBookingService
from payments.exceptions import BookingClientError, BookingValidationError
from services_app.models import GiftCertificate, Order
from website.notifications import send_certificate_email, send_notification_telegram

logger = logging.getLogger(__name__)


@shared_task(
    name="payments.tasks.fulfill_paid_order",
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    ignore_result=True,
)
def fulfill_paid_order(self, order_id: int):
    """Создать YClients-запись под оплаченный Order.

    Идемпотентно через YClientsBookingService.create_record — повторный
    вызов с заполненным order.yclients_record_id ничего не делает.
    """
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        logger.error("fulfill_paid_order: order id=%s not found", order_id)
        return

    if order.yclients_record_id:
        logger.info(
            "fulfill_paid_order: order=%s already has record_id=%s, skip",
            order.number, order.yclients_record_id,
        )
        return

    try:
        result = YClientsBookingService().create_record(order)
    except BookingValidationError as exc:
        # Фатально — нет смысла ретраить, ручной разбор нужен.
        logger.exception(
            "fulfill_paid_order: validation failed for order=%s: %s",
            order.number, exc,
        )
        _append_admin_note(order, f"[fulfill] validation: {exc}")
        send_notification_telegram(
            f"❌ QC failed для заказа {order.number}: {exc}\n"
            f"Нужен ручной разбор — данные для записи в YClients неполные."
        )
        return
    except BookingClientError as exc:
        # YClients временно недоступен / слот занят / сетевой сбой — retry.
        logger.warning(
            "fulfill_paid_order: YClients failed for order=%s, retry=%s: %s",
            order.number, self.request.retries, exc,
        )
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error(
                "fulfill_paid_order: max retries exceeded for order=%s",
                order.number,
            )
            _append_admin_note(order, f"[fulfill] max retries: {exc}")
            send_notification_telegram(
                f"❌ Не удалось создать запись в YClients для оплаченного заказа "
                f"{order.number} после {self.max_retries} попыток: {exc}\n"
                f"Сумма: {order.total_amount} ₽ — нужен ручной ввод в YClients или refund."
            )
            return

    # Успех: уведомляем админа что можно готовиться к приёму клиента.
    send_notification_telegram(
        f"✅ Оплата {order.total_amount} ₽ получена, запись создана: {order.number}\n"
        f"Клиент: {order.client_name} {order.client_phone}\n"
        f"Мастер ID: {order.staff_id}, время: {order.scheduled_at:%d.%m.%Y %H:%M}\n"
        f"YClients record: {result['record_id']}"
    )


@shared_task(
    name="payments.tasks.fulfill_paid_certificate",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    ignore_result=True,
)
def fulfill_paid_certificate(self, order_id: int):
    """Активировать сертификат после успешной оплаты, уведомить админа и покупателя."""
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        logger.error("fulfill_paid_certificate: order id=%s not found", order_id)
        return

    try:
        cert = GiftCertificate.objects.get(order=order)
    except GiftCertificate.DoesNotExist:
        logger.error("fulfill_paid_certificate: no certificate for order=%s", order.number)
        return

    if cert.status == "paid":
        logger.info("fulfill_paid_certificate: order=%s already paid, skip", order.number)
        return

    cert.status = "paid"
    cert.paid_at = timezone.now()
    cert.is_active = True
    cert.save(update_fields=["status", "paid_at", "is_active", "updated_at"])

    value_str = (
        f"{cert.nominal:,.0f} ₽".replace(",", " ")
        if cert.certificate_type == "nominal"
        else str(cert.service)
    )
    send_notification_telegram(
        f"🎁 Сертификат оплачен: {cert.code}\n"
        f"Тип: {cert.get_certificate_type_display()} — {value_str}\n"
        f"Покупатель: {order.client_name} {order.client_phone}\n"
        f"Получатель: {cert.recipient_name or '—'} {cert.recipient_phone or ''}\n"
        f"Действителен до: {cert.valid_until}\n"
        f"Заказ: {order.number}"
    )

    if order.client_email:
        send_certificate_email(order, cert)

    logger.info("fulfill_paid_certificate: order=%s cert=%s activated", order.number, cert.code)


@shared_task(
    name="payments.tasks.fulfill_paid_bundle",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    ignore_result=True,
)
def fulfill_paid_bundle(self, order_id: int):
    """Подтвердить оплату комплекса, уведомить админа."""
    try:
        order = Order.objects.select_related("bundle").get(pk=order_id)
    except Order.DoesNotExist:
        logger.error("fulfill_paid_bundle: order id=%s not found", order_id)
        return

    bundle = order.bundle
    send_notification_telegram(
        f"📦 Комплекс оплачен: {bundle.name if bundle else '—'}\n"
        f"Сумма: {order.total_amount} ₽\n"
        f"Клиент: {order.client_name} {order.client_phone}\n"
        f"Email: {order.client_email or '—'}\n"
        f"Заказ: {order.number}\n"
        f"⚠️ Запись на сессии — вручную через YClients"
    )
    logger.info("fulfill_paid_bundle: order=%s notified", order.number)


def _append_admin_note(order: Order, text: str) -> None:
    existing = order.admin_note or ""
    order.admin_note = (existing + "\n" + text).strip()
    order.save(update_fields=["admin_note", "updated_at"])
