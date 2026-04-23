"""Unit-тесты YClientsBookingService.

Мокается YClientsAPI (через DI в конструктор) — реальный YClients API не
дёргается. Паттерн моков — как mock_yclients_api в conftest.py.
"""
from unittest.mock import MagicMock

import pytest

from payments.booking_service import YClientsBookingService
from payments.exceptions import BookingClientError, BookingValidationError
from services_app.yclients_api import YClientsAPIError


@pytest.fixture
def fake_yclients():
    """Мок YClientsAPI.create_booking, возвращает успешный booking-ответ."""
    api = MagicMock()
    api.create_booking.return_value = {
        "record_id": 98765,
        "record_hash": "abc123hash",
    }
    return api


class TestCreateRecordHappyPath:
    def test_calls_yclients_create_booking(self, fake_yclients, service_order):
        svc = YClientsBookingService(api=fake_yclients)
        svc.create_record(service_order)
        fake_yclients.create_booking.assert_called_once()

    def test_returns_record_id_and_hash(self, fake_yclients, service_order):
        svc = YClientsBookingService(api=fake_yclients)
        result = svc.create_record(service_order)
        assert result == {"record_id": "98765", "record_hash": "abc123hash"}

    def test_persists_record_on_order(self, fake_yclients, service_order):
        svc = YClientsBookingService(api=fake_yclients)
        svc.create_record(service_order)
        service_order.refresh_from_db()
        assert service_order.yclients_record_id == "98765"
        assert service_order.yclients_record_hash == "abc123hash"

    def test_passes_staff_id_and_service_id(self, fake_yclients, service_order):
        svc = YClientsBookingService(api=fake_yclients)
        svc.create_record(service_order)
        kwargs = fake_yclients.create_booking.call_args.kwargs
        assert kwargs["staff_id"] == service_order.staff_id
        # yclients_service_id из фикстуры service_option = "10000001"
        assert kwargs["services"] == [10000001]

    def test_passes_client_dict(self, fake_yclients, service_order):
        svc = YClientsBookingService(api=fake_yclients)
        svc.create_record(service_order)
        client = fake_yclients.create_booking.call_args.kwargs["client"]
        assert client == {
            "name": service_order.client_name,
            "phone": service_order.client_phone,
            "email": service_order.client_email or "",
        }

    def test_passes_datetime_iso_without_tz(self, fake_yclients, service_order):
        svc = YClientsBookingService(api=fake_yclients)
        svc.create_record(service_order)
        dt_str = fake_yclients.create_booking.call_args.kwargs["datetime"]
        # ISO-формат YYYY-MM-DDTHH:MM:SS, без tz-суффикса
        assert "T" in dt_str
        assert dt_str.count(":") == 2
        assert "+" not in dt_str and "Z" not in dt_str

    def test_passes_comment(self, fake_yclients, service_order):
        service_order.comment = "Впервые в салоне"
        service_order.save(update_fields=["comment"])
        svc = YClientsBookingService(api=fake_yclients)
        svc.create_record(service_order)
        assert fake_yclients.create_booking.call_args.kwargs["comment"] == "Впервые в салоне"


class TestCreateRecordIdempotency:
    def test_skip_api_when_already_booked(self, fake_yclients, service_order):
        service_order.yclients_record_id = "existing-999"
        service_order.yclients_record_hash = "existing-hash"
        service_order.save(update_fields=["yclients_record_id", "yclients_record_hash"])

        svc = YClientsBookingService(api=fake_yclients)
        result = svc.create_record(service_order)

        fake_yclients.create_booking.assert_not_called()
        assert result == {"record_id": "existing-999", "record_hash": "existing-hash"}


class TestCreateRecordValidation:
    def test_raises_when_no_staff_id(self, fake_yclients, service_order):
        service_order.staff_id = None
        service_order.save(update_fields=["staff_id"])
        svc = YClientsBookingService(api=fake_yclients)
        with pytest.raises(BookingValidationError):
            svc.create_record(service_order)
        fake_yclients.create_booking.assert_not_called()

    def test_raises_when_no_scheduled_at(self, fake_yclients, service_order):
        service_order.scheduled_at = None
        service_order.save(update_fields=["scheduled_at"])
        svc = YClientsBookingService(api=fake_yclients)
        with pytest.raises(BookingValidationError):
            svc.create_record(service_order)

    def test_raises_when_no_service_option(self, fake_yclients, service_order):
        service_order.service_option = None
        service_order.save(update_fields=["service_option"])
        svc = YClientsBookingService(api=fake_yclients)
        with pytest.raises(BookingValidationError):
            svc.create_record(service_order)

    def test_raises_when_yclients_service_id_empty(self, fake_yclients, service_order):
        service_order.service_option.yclients_service_id = ""
        service_order.service_option.save(update_fields=["yclients_service_id"])
        svc = YClientsBookingService(api=fake_yclients)
        with pytest.raises(BookingValidationError):
            svc.create_record(service_order)

    def test_raises_when_yclients_service_id_not_int(self, fake_yclients, service_order):
        service_order.service_option.yclients_service_id = "not-a-number"
        service_order.service_option.save(update_fields=["yclients_service_id"])
        svc = YClientsBookingService(api=fake_yclients)
        with pytest.raises(BookingValidationError):
            svc.create_record(service_order)


class TestCreateRecordErrors:
    def test_wraps_yclients_api_error(self, fake_yclients, service_order):
        fake_yclients.create_booking.side_effect = YClientsAPIError("slot taken")
        svc = YClientsBookingService(api=fake_yclients)
        with pytest.raises(BookingClientError):
            svc.create_record(service_order)

    def test_raises_when_yclients_returns_empty_record_id(self, fake_yclients, service_order):
        fake_yclients.create_booking.return_value = {"record_id": None, "record_hash": "x"}
        svc = YClientsBookingService(api=fake_yclients)
        with pytest.raises(BookingClientError):
            svc.create_record(service_order)

    def test_order_not_persisted_when_api_fails(self, fake_yclients, service_order):
        fake_yclients.create_booking.side_effect = YClientsAPIError("nope")
        svc = YClientsBookingService(api=fake_yclients)
        with pytest.raises(BookingClientError):
            svc.create_record(service_order)
        service_order.refresh_from_db()
        assert service_order.yclients_record_id == ""

    def test_422_parsed_as_validation_with_human_message(self, fake_yclients, service_order):
        # 4xx от YClients с meta.message — это бизнес-ошибка (время занято и т.п.).
        # Должно стать BookingValidationError с человеческим сообщением, чтобы
        # показать клиенту без технических деталей.
        fake_yclients.create_booking.side_effect = YClientsAPIError(
            'HTTP 422: {"success":false,"data":null,'
            '"meta":{"message":"Услуга недоступна в выбранное время. Выберите другое время."}}'
        )
        svc = YClientsBookingService(api=fake_yclients)
        with pytest.raises(BookingValidationError) as exc_info:
            svc.create_record(service_order)
        assert "Услуга недоступна в выбранное время" in str(exc_info.value)

    def test_5xx_stays_as_client_error(self, fake_yclients, service_order):
        # 5xx — реальная проблема YClients, не показываем деталь клиенту.
        fake_yclients.create_booking.side_effect = YClientsAPIError(
            'HTTP 503: {"meta":{"message":"service unavailable"}}'
        )
        svc = YClientsBookingService(api=fake_yclients)
        with pytest.raises(BookingClientError):
            svc.create_record(service_order)
