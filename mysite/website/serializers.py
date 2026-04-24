"""DRF serializers для customer-facing API website.

Input serializers (валидация payload):
- ServiceOrderCreateSerializer — POST /api/services/order/

Output serializers (закрепляют JSON-контракт ответа, защищают от
случайного field leak когда модели расширяются):
- WizardCategorySerializer        — /api/wizard/categories/
- WizardServiceSerializer         — /api/wizard/categories/<id>/services/
- ServiceOptionResponseSerializer — /api/booking/service_options/
- StaffSerializer                 — /api/booking/get_staff/   (data — dict от YClients, не модель)
- BookingCreateResponseSerializer — /api/booking/create/      (data — dict от YClients + контекст view)
"""
from datetime import datetime, time as dt_time

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from services_app.models import ServiceOption
from website.utils import normalize_ru_phone


class ServiceOrderCreateSerializer(serializers.Serializer):
    """Payload для POST /api/services/order/.

    Клиент выбирает услугу (ServiceOption), мастера/дату/время, контакты и
    способ оплаты. Серверная валидация:
    - service_option_id — существует, is_active, price > 0
    - staff_id, date/time — корректные форматы
    - phone — нормализуется до +7XXXXXXXXXX
    - payment_method — один из online/cash/card_offline
    """
    service_option_id = serializers.IntegerField(min_value=1)
    staff_id = serializers.IntegerField(min_value=1)
    date = serializers.DateField()
    time = serializers.CharField(max_length=5)
    client_name = serializers.CharField(max_length=150)
    client_phone = serializers.CharField(max_length=30)
    client_email = serializers.EmailField(required=False, allow_blank=True, default="")
    comment = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=2000
    )
    payment_method = serializers.ChoiceField(
        choices=["online", "cash", "card_offline"]
    )

    def validate_time(self, value):
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            raise serializers.ValidationError("time must be HH:MM")
        return value

    def validate_client_phone(self, value):
        try:
            return normalize_ru_phone(value)
        except DjangoValidationError as exc:
            msg = getattr(exc, "message", None) or str(exc)
            raise serializers.ValidationError(msg)

    def validate_service_option_id(self, value):
        try:
            option = ServiceOption.objects.select_related("service").get(
                id=value, is_active=True
            )
        except ServiceOption.DoesNotExist:
            raise serializers.ValidationError("service_option not found or inactive")
        if option.price <= 0:
            raise serializers.ValidationError("service_option has no price")
        return value

    def validate(self, attrs):
        # Собираем scheduled_at из date + time в локальной таймзоне салона.
        hh, mm = attrs["time"].split(":")
        naive = datetime.combine(attrs["date"], dt_time(int(hh), int(mm)))
        attrs["scheduled_at"] = timezone.make_aware(
            naive, timezone.get_current_timezone()
        )
        # Подтягиваем ServiceOption объект в validated_data для удобства view.
        attrs["service_option"] = ServiceOption.objects.select_related("service").get(
            id=attrs["service_option_id"]
        )
        return attrs


# ── Output serializers ──────────────────────────────────────────────────────
# Закрепляют JSON-контракт ответа. View собирает source-объект (модель или
# dict) и передаёт в `Serializer(obj).data` — лишние поля не утекают.


class WizardCategorySerializer(serializers.Serializer):
    """Категория услуг для формы-мастера: id, имя, число активных услуг."""
    id = serializers.IntegerField()
    name = serializers.CharField()
    services_count = serializers.IntegerField()


class WizardServiceSerializer(serializers.Serializer):
    """Услуга для формы-мастера + первый активный вариант (цена/длительность).

    `duration`/`price`/`option_id` — None, если у услуги нет активных опций.
    """
    id = serializers.IntegerField()
    name = serializers.CharField()
    duration = serializers.IntegerField(allow_null=True)
    price = serializers.IntegerField(allow_null=True)
    option_id = serializers.IntegerField(allow_null=True)


class ServiceOptionResponseSerializer(serializers.Serializer):
    """ServiceOption для модалки бронирования: длительность, кол-во, цена."""
    id = serializers.IntegerField()
    duration = serializers.IntegerField(source="duration_min")
    quantity = serializers.IntegerField(source="units")
    unit_type = serializers.CharField()
    unit_type_display = serializers.CharField(source="get_unit_type_display")
    price = serializers.FloatField()
    yclients_id = serializers.SerializerMethodField()

    def get_yclients_id(self, obj):
        return obj.yclients_service_id or ""


class StaffSerializer(serializers.Serializer):
    """Мастер из YClients (источник — dict, не модель Django)."""
    id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField(allow_blank=True, default="")
    specialization = serializers.CharField(allow_blank=True, default="")
    avatar = serializers.CharField(allow_blank=True, default="")
    rating = serializers.FloatField(default=0)


class BookingCreateResponseSerializer(serializers.Serializer):
    """Ответ POST /api/booking/create/ — поля из YClients + контекст view."""
    booking_id = serializers.IntegerField(allow_null=True)
    booking_hash = serializers.CharField(allow_blank=True, default="")
    staff_id = serializers.IntegerField()
    staff_name = serializers.CharField(allow_blank=True, default="")
    datetime = serializers.CharField()
    service_ids = serializers.ListField(child=serializers.IntegerField())
    client_name = serializers.CharField()
    comment = serializers.CharField(allow_blank=True, default="")
