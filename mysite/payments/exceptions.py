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
