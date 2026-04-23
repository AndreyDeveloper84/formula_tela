"""YClientsBookingService — создание YClients-записи под Order.

Shared service: используется и в offline-flow (payment_method=cash/card_offline,
запись создаётся сразу в endpoint'е) и в online-flow (после paid webhook'а,
запись создаётся из Celery task в payments/tasks.py — PR #4).

Идемпотентный: если Order.yclients_record_id уже заполнен — повторный вызов
не дёргает YClients API, возвращает существующий record_id/hash. Нужно для
защиты от двойной обработки webhook и Celery retry.
"""
import json
import logging
import re

from django.utils import timezone

from payments.exceptions import BookingClientError, BookingValidationError
from services_app.models import Order
from services_app.yclients_api import YClientsAPI, YClientsAPIError, get_yclients_api

logger = logging.getLogger(__name__)

# Текст YClientsAPIError имеет вид "HTTP 422: {...json...}" (см. yclients_api._request).
_HTTP_STATUS_RE = re.compile(r"^HTTP (\d{3}):\s*(.*)$", re.DOTALL)


def _parse_yclients_error(exc: YClientsAPIError) -> tuple[int | None, str]:
    """Извлечь HTTP-статус и meta.message из текста YClientsAPIError.

    Возвращает (status, human_message). Если парсинг не удался — (None, str(exc)).
    """
    m = _HTTP_STATUS_RE.match(str(exc))
    if not m:
        return None, str(exc)
    try:
        status = int(m.group(1))
    except ValueError:
        return None, str(exc)
    body = m.group(2)
    try:
        payload = json.loads(body)
        meta_msg = (payload.get("meta") or {}).get("message")
        if meta_msg:
            return status, meta_msg
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return status, body or str(exc)


class YClientsBookingService:
    def __init__(self, api: YClientsAPI | None = None):
        self._api = api or get_yclients_api()

    def create_record(self, order: Order) -> dict:
        """Создать запись в YClients под Order. Идемпотентный.

        Обновляет Order.yclients_record_id / yclients_record_hash.
        Возвращает {"record_id", "record_hash"}.
        """
        if order.yclients_record_id:
            logger.info(
                "YClientsBookingService: order=%s already has record_id=%s, skip",
                order.number, order.yclients_record_id,
            )
            return {
                "record_id": order.yclients_record_id,
                "record_hash": order.yclients_record_hash,
            }

        self._validate(order)
        yclients_service_id = self._extract_service_id(order)
        booking_datetime = self._format_datetime(order.scheduled_at)
        client = self._build_client(order)

        logger.info(
            "YClientsBookingService: creating record for order=%s staff=%s datetime=%s",
            order.number, order.staff_id, booking_datetime,
        )
        try:
            booking = self._api.create_booking(
                staff_id=order.staff_id,
                services=[yclients_service_id],
                datetime=booking_datetime,
                client=client,
                comment=order.comment or "",
            )
        except YClientsAPIError as exc:
            status, human_msg = _parse_yclients_error(exc)
            # 4xx = validation (неправильные данные от клиента): выбранное время
            # занято, мастер не оказывает услугу, и т.п. Показываем сообщение
            # от YClients клиенту как есть. 5xx и прочие — реальная проблема.
            if status is not None and 400 <= status < 500:
                logger.warning(
                    "YClientsBookingService: validation error for order=%s (HTTP %s): %s",
                    order.number, status, human_msg,
                )
                raise BookingValidationError(human_msg) from exc
            logger.exception(
                "YClientsBookingService: YClients failed for order=%s: %s",
                order.number, exc,
            )
            raise BookingClientError(
                f"YClients error for order {order.number}: {human_msg}"
            ) from exc

        record_id = str(booking.get("record_id") or "")
        record_hash = str(booking.get("record_hash") or "")
        if not record_id:
            raise BookingClientError(
                f"YClients returned empty record_id for order {order.number}"
            )

        order.yclients_record_id = record_id
        order.yclients_record_hash = record_hash
        order.save(update_fields=["yclients_record_id", "yclients_record_hash", "updated_at"])
        logger.info(
            "YClientsBookingService: order=%s → record_id=%s",
            order.number, record_id,
        )
        return {"record_id": record_id, "record_hash": record_hash}

    # ── Валидация и билдеры ───────────────────────────────────────────

    def _validate(self, order: Order) -> None:
        if not order.staff_id:
            raise BookingValidationError(
                f"Order {order.number}: staff_id is required for YClients booking"
            )
        if not order.scheduled_at:
            raise BookingValidationError(
                f"Order {order.number}: scheduled_at is required"
            )
        if not order.service_option_id:
            raise BookingValidationError(
                f"Order {order.number}: service_option is required"
            )

    def _extract_service_id(self, order: Order) -> int:
        raw = (order.service_option.yclients_service_id or "").strip()
        if not raw:
            raise BookingValidationError(
                f"Order {order.number}: service_option {order.service_option_id} has empty "
                "yclients_service_id — нельзя создать запись в YClients"
            )
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise BookingValidationError(
                f"Order {order.number}: yclients_service_id={raw!r} is not int"
            ) from exc

    def _format_datetime(self, dt) -> str:
        """YClients принимает datetime строкой в локальном времени салона.

        Конвертируем naive/aware datetime в TIME_ZONE (salon's local) и
        отдаём ISO-формат без tz-суффикса — так делает существующий
        api_create_booking view.
        """
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        local = timezone.localtime(dt)
        return local.strftime("%Y-%m-%dT%H:%M:%S")

    def _build_client(self, order: Order) -> dict:
        return {
            "name": order.client_name,
            "phone": order.client_phone,
            "email": order.client_email or "",
        }
