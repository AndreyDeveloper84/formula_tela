"""Иерархия исключений подсистемы оплат.

Позволяет caller'у ловить точечно: ошибку конфигурации (нет creds) отдельно от
ошибки удалённого API отдельно от доменной ошибки (например, amount <= 0).
"""


class PaymentError(Exception):
    """Базовая доменная ошибка оплат."""


class PaymentConfigError(PaymentError):
    """YooKassa не настроена — пустой SHOP_ID или SECRET_KEY."""


class PaymentClientError(PaymentError):
    """Ошибка при общении с YooKassa API (обёртка над yookassa.ApiError)."""


class BookingError(PaymentError):
    """Доменная ошибка создания записи в YClients после оплаты/без оплаты."""


class BookingValidationError(BookingError):
    """Order не содержит данных, нужных для записи (staff_id/scheduled_at/service_option)."""


class BookingClientError(BookingError):
    """Ошибка при общении с YClients (обёртка над services_app.yclients_api.YClientsAPIError)."""
