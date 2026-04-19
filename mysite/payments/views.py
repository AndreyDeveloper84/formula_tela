"""HTTP-views подсистемы оплат.

Пока единственный view — webhook YooKassa. Customer-facing endpoints
(/api/services/order/, /api/payments/status/) появятся в PR #5.
"""
import json
import logging

from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from payments.exceptions import PaymentClientError, PaymentConfigError
from payments.ip_whitelist import yookassa_ip_only
from payments.tasks import fulfill_paid_bundle, fulfill_paid_certificate, fulfill_paid_order
from payments.yookassa_client import get_yookassa_client
from services_app.models import Order
from website.notifications import send_notification_telegram

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
@yookassa_ip_only
@ratelimit(key="ip", rate="120/m", method="POST", block=True)
def yookassa_webhook(request):
    """Принимает callback от YooKassa при смене статуса платежа.

    Flow:
      1. Parse JSON payload, извлечь payment.id
      2. Verify через YooKassaClient.find_payment(id) — double-check
         подлинности (spoofed POST отсекается)
      3. Найти Order по payment_id; если нет — логируем и 200 (YooKassa
         не должна ретраить из-за отсутствия заказа на нашей стороне)
      4. По статусу:
         - succeeded: Order.payment_status=succeeded, paid_at=now(),
           status=paid, fulfill_paid_order.delay(order.id)
         - canceled:  Order.payment_status=canceled, Telegram админу
         - прочие: игнорируем
      5. Всегда 200, чтобы YooKassa не спамила retry

    Идемпотентно: повторная доставка того же события для уже-succeeded
    заказа не дёргает fulfill второй раз.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("yookassa_webhook: invalid JSON from %s", request.META.get("REMOTE_ADDR"))
        return HttpResponseBadRequest("invalid json")

    payment_obj = payload.get("object") or {}
    payment_id = payment_obj.get("id")
    if not payment_id:
        logger.warning("yookassa_webhook: missing payment id")
        return HttpResponseBadRequest("missing payment id")

    # Verify через API — защита от spoofed POST.
    try:
        client = get_yookassa_client()
        verified = client.find_payment(payment_id)
    except PaymentConfigError:
        logger.error("yookassa_webhook: YOOKASSA creds missing — ответ 503")
        return HttpResponse(status=503)
    except PaymentClientError as exc:
        logger.error("yookassa_webhook: verify failed for %s: %s", payment_id, exc)
        return HttpResponse(status=502)

    status = verified.get("status", "")
    try:
        order = Order.objects.get(payment_id=payment_id)
    except Order.DoesNotExist:
        logger.warning(
            "yookassa_webhook: order not found for payment_id=%s (status=%s)",
            payment_id, status,
        )
        return JsonResponse({"detail": "order not found"}, status=200)

    if status == "succeeded":
        _handle_succeeded(order)
    elif status == "canceled":
        _handle_canceled(order, order_type=order.order_type)
    else:
        logger.info(
            "yookassa_webhook: order=%s status=%s — no-op",
            order.number, status,
        )

    return JsonResponse({"ok": True}, status=200)


def _handle_succeeded(order: Order) -> None:
    if order.payment_status == "succeeded":
        logger.info("yookassa_webhook: order=%s already succeeded, skip", order.number)
        return
    order.payment_status = "succeeded"
    order.status = "paid"
    order.paid_at = timezone.now()
    order.save(update_fields=["payment_status", "status", "paid_at", "updated_at"])

    if order.order_type == "certificate":
        fulfill_paid_certificate.delay(order.id)
    elif order.order_type == "bundle":
        fulfill_paid_bundle.delay(order.id)
    else:
        fulfill_paid_order.delay(order.id)

    logger.info(
        "yookassa_webhook: order=%s (type=%s) → succeeded, fulfill scheduled",
        order.number, order.order_type,
    )


def _handle_canceled(order: Order, order_type: str = "service") -> None:
    if order.payment_status == "canceled":
        return
    order.payment_status = "canceled"
    order.status = "cancelled"
    order.save(update_fields=["payment_status", "status", "updated_at"])
    labels = {"certificate": "Сертификат", "bundle": "Комплекс"}
    label = labels.get(order_type, "Заказ")
    send_notification_telegram(
        f"⚠️ Платёж отменён: {label} {order.number} ({order.total_amount} ₽)"
    )
    logger.info("yookassa_webhook: order=%s → canceled", order.number)


@require_GET
def payment_success_page(request):
    """HTML-страница, на которую редиректит YooKassa после оплаты.

    Читает ?order=<number>, пробрасывает номер в шаблон; JS-поллер
    (см. static/js/payment-status-poll.js) опрашивает /api/payments/status/
    до fulfilled=True.
    """
    order_number = request.GET.get("order", "").strip()
    return render(request, "payments/success.html", {"order_number": order_number})


@require_GET
def payment_cancelled_page(request):
    """HTML-страница для отменённого платежа. Показывается когда клиент
    закрыл окно YooKassa или платёж canceled. Предлагает оплатить заново
    или выбрать другой способ."""
    order_number = request.GET.get("order", "").strip()
    return render(request, "payments/cancelled.html", {"order_number": order_number})


@require_GET
def payment_status(request):
    """GET /api/payments/status/?order=<number>

    Лёгкий endpoint для polling со страницы /payments/success/.
    Фронт дёргает его каждые 2-3 сек и ждёт payment_status=succeeded +
    fulfilled=True (YClients record создан).
    """
    order_number = request.GET.get("order", "").strip()
    if not order_number:
        return HttpResponseBadRequest("order param required")
    try:
        order = Order.objects.only(
            "number", "payment_status", "status", "yclients_record_id"
        ).get(number=order_number)
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "error": "not found"}, status=404)
    return JsonResponse({
        "success": True,
        "order_number": order.number,
        "payment_status": order.payment_status,
        "order_status": order.status,
        "yclients_record_id": order.yclients_record_id,
        "fulfilled": bool(order.yclients_record_id),
    })
